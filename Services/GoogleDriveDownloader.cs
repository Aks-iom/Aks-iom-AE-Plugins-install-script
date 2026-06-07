using System;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Generic;
using System.Linq;

namespace AEPluginInstaller.Services;

/// <summary>
/// Скачивает файлы с Google Drive по публичной ссылке (без Google API).
/// Поддерживает:
///   - короткие ссылки вида https://drive.google.com/file/d/FILE_ID/view
///   - ссылки uc?export=download&id=FILE_ID
///   - обход confirm-страницы для файлов >100 МБ (virus scan warning)
/// </summary>
public class GoogleDriveDownloader : IDisposable
{
    private readonly HttpClient _http;
    private readonly CookieContainer _cookies = new();

    public GoogleDriveDownloader()
    {
        var handler = new HttpClientHandler
        {
            CookieContainer = _cookies,
            AllowAutoRedirect = true,
            AutomaticDecompression = DecompressionMethods.All
        };
        _http = new HttpClient(handler)
        {
            // Большие файлы качаются десятками минут — стандартный 100с-таймаут не годится.
            // Длительность отдельных операций контролируется CancellationToken-ами.
            Timeout = Timeout.InfiniteTimeSpan
        };
        _http.DefaultRequestHeaders.UserAgent.ParseAdd(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36");
    }

    /// <summary>Достаёт FILE_ID из любого формата ссылки. Доступен снаружи для проверки кэша.</summary>
    public static string? ExtractFileId(string url)
    {
        if (string.IsNullOrWhiteSpace(url)) return null;

        // /file/d/FILE_ID/...
        var m = Regex.Match(url, @"\/file\/d\/([a-zA-Z0-9_-]+)");
        if (m.Success) return m.Groups[1].Value;

        // ?id=FILE_ID или &id=FILE_ID
        m = Regex.Match(url, @"[?&]id=([a-zA-Z0-9_-]+)");
        if (m.Success) return m.Groups[1].Value;

        // /open?id=... или /uc?id=...
        m = Regex.Match(url, @"\/(?:open|uc)\?[^#]*id=([a-zA-Z0-9_-]+)");
        if (m.Success) return m.Groups[1].Value;

        // Если уже передан голый ID
        if (Regex.IsMatch(url, @"^[a-zA-Z0-9_-]{20,}$")) return url;

        return null;
    }

    public async Task<string> DownloadAsync(
        string driveUrl,
        string destinationFolder,
        IProgress<DownloadProgress>? progress = null,
        CancellationToken ct = default)
    {
        var fileId = ExtractFileId(driveUrl)
            ?? throw new InvalidOperationException($"Не удалось извлечь ID из ссылки: {driveUrl}");

        Directory.CreateDirectory(destinationFolder);

        const int maxAttempts = 6;
        string? fileName = null;
        string? destPath = null;
        string? partPath = null;
        long total = -1L;
        Exception? lastError = null;

        for (int attempt = 1; attempt <= maxAttempts; attempt++)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                long resumeFrom = 0;
                if (partPath != null && File.Exists(partPath))
                    resumeFrom = new FileInfo(partPath).Length;

                using var response = await OpenDownloadAsync(fileId, resumeFrom, ct);

                if (fileName == null)
                {
                    fileName = GetFileNameFromResponse(response) ?? $"{fileId}.bin";
                    destPath = Path.Combine(destinationFolder, fileName);
                    partPath = destPath + ".part";
                }

                bool isResume = response.StatusCode == HttpStatusCode.PartialContent;

                if (total < 0)
                {
                    if (isResume && response.Content.Headers.ContentRange?.Length is long lc)
                        total = lc;
                    else if (!isResume)
                        total = response.Content.Headers.ContentLength ?? -1L;
                }

                // Сервер не уважил Range — придётся качать заново
                if (resumeFrom > 0 && !isResume)
                {
                    try { File.Delete(partPath!); } catch { }
                    resumeFrom = 0;
                }

                await using (var input = await response.Content.ReadAsStreamAsync(ct))
                await using (var output = new FileStream(
                    partPath!,
                    isResume && resumeFrom > 0 ? FileMode.Append : FileMode.Create,
                    FileAccess.Write, FileShare.None, 81920, useAsync: true))
                {
                    var buffer = new byte[81920];
                    long downloaded = resumeFrom;
                    int read;
                    var lastReport = DateTime.UtcNow;

                    while ((read = await input.ReadAsync(buffer, ct)) > 0)
                    {
                        await output.WriteAsync(buffer.AsMemory(0, read), ct);
                        downloaded += read;

                        if (progress != null && (DateTime.UtcNow - lastReport).TotalMilliseconds > 100)
                        {
                            progress.Report(new DownloadProgress(downloaded, total, fileName));
                            lastReport = DateTime.UtcNow;
                        }
                    }

                    progress?.Report(new DownloadProgress(downloaded, total, fileName));
                }

                if (File.Exists(destPath!)) File.Delete(destPath!);
                File.Move(partPath!, destPath!);
                return destPath!;
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                throw;
            }
            catch (Exception ex) when (attempt < maxAttempts && IsTransient(ex))
            {
                lastError = ex;
                var delaySec = Math.Min(30, (int)Math.Pow(2, attempt));
                await Task.Delay(TimeSpan.FromSeconds(delaySec), ct);
            }
        }

        throw new IOException(
            $"Скачивание прервано после {maxAttempts} попыток: {lastError?.Message}",
            lastError);
    }

    private static bool IsTransient(Exception ex)
    {
        // Сетевые обрывы, EOF посреди стрима, таймауты сокета — всё это лечится повтором с Range.
        for (var e = ex; e != null; e = e.InnerException!)
        {
            if (e is HttpRequestException or IOException or System.Net.Sockets.SocketException
                or System.IO.IOException)
                return true;
            if (e is TaskCanceledException tce && tce.InnerException is TimeoutException)
                return true;
            if (e.InnerException == null) break;
        }
        return false;
    }

    private async Task<HttpResponseMessage> OpenDownloadAsync(string fileId, long resumeFrom, CancellationToken ct)
    {
        var url = $"https://drive.google.com/uc?export=download&id={fileId}";
        var response = await SendWithRangeAsync(url, HttpMethod.Get, resumeFrom, ct);

        if (IsHtmlResponse(response))
        {
            response.Dispose();
            response = await HandleConfirmationPage(fileId, resumeFrom, ct);
        }

        response.EnsureSuccessStatusCode();
        return response;
    }

    private async Task<HttpResponseMessage> SendWithRangeAsync(
        string url, HttpMethod method, long resumeFrom, CancellationToken ct)
    {
        var req = new HttpRequestMessage(method, url);
        if (resumeFrom > 0)
            req.Headers.Range = new RangeHeaderValue(resumeFrom, null);
        return await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct);
    }

    private async Task<HttpResponseMessage> HandleConfirmationPage(string fileId, long resumeFrom, CancellationToken ct)
    {
        // Получаем HTML страницы подтверждения
        var pageUrl = $"https://drive.google.com/uc?export=download&id={fileId}";
        var html = await _http.GetStringAsync(pageUrl, ct);

        // Формат 1 (старый): ссылка с &confirm=XXXX в HTML
        var m = Regex.Match(html, @"confirm=([0-9A-Za-z_-]+)");
        if (m.Success)
        {
            var confirmUrl = $"https://drive.google.com/uc?export=download&confirm={m.Groups[1].Value}&id={fileId}";
            var resp = await SendWithRangeAsync(confirmUrl, HttpMethod.Get, resumeFrom, ct);
            if (!IsHtmlResponse(resp)) return resp;
            resp.Dispose();
        }

        // Формат 2 (новый, 2022+): форма POST на https://drive.usercontent.google.com/download
        var formMatch = Regex.Match(html,
            @"<form[^>]*action=""([^""]+)""[^>]*>(.*?)</form>",
            RegexOptions.Singleline | RegexOptions.IgnoreCase);

        if (formMatch.Success)
        {
            var action = WebUtility.HtmlDecode(formMatch.Groups[1].Value);
            var formBody = formMatch.Groups[2].Value;

            var inputs = Regex.Matches(formBody,
                @"<input[^>]*name=""([^""]+)""[^>]*value=""([^""]*)""",
                RegexOptions.IgnoreCase);

            var query = new List<string>();
            foreach (Match input in inputs)
            {
                var name = WebUtility.HtmlDecode(input.Groups[1].Value);
                var value = WebUtility.HtmlDecode(input.Groups[2].Value);
                query.Add($"{Uri.EscapeDataString(name)}={Uri.EscapeDataString(value)}");
            }

            var finalUrl = action + (action.Contains('?') ? "&" : "?") + string.Join("&", query);
            return await SendWithRangeAsync(finalUrl, HttpMethod.Get, resumeFrom, ct);
        }

        throw new InvalidOperationException(
            "Не удалось обойти страницу подтверждения Google Drive. " +
            "Проверь, что файл расшарен по ссылке (Anyone with the link).");
    }

    private static bool IsHtmlResponse(HttpResponseMessage r)
    {
        var ct = r.Content.Headers.ContentType?.MediaType;
        return ct != null && ct.StartsWith("text/html", StringComparison.OrdinalIgnoreCase);
    }

    private static string? GetFileNameFromResponse(HttpResponseMessage r)
    {
        // Content-Disposition: attachment; filename="name.zip"; filename*=UTF-8''name.zip
        var cd = r.Content.Headers.ContentDisposition;
        if (cd != null)
        {
            var name = cd.FileNameStar ?? cd.FileName;
            if (!string.IsNullOrEmpty(name))
                return SanitizeFileName(name.Trim('"'));
        }

        // Резерв — ищем в заголовке вручную
        if (r.Content.Headers.TryGetValues("Content-Disposition", out var values))
        {
            foreach (var v in values)
            {
                var m = Regex.Match(v, @"filename\*?=(?:UTF-8'')?""?([^"";]+)""?");
                if (m.Success)
                    return SanitizeFileName(Uri.UnescapeDataString(m.Groups[1].Value));
            }
        }

        return null;
    }

    private static string SanitizeFileName(string name)
    {
        foreach (var c in Path.GetInvalidFileNameChars())
            name = name.Replace(c, '_');
        return name;
    }

    public void Dispose() => _http.Dispose();
}

public record DownloadProgress(long Bytes, long Total, string FileName)
{
    public double Percent => Total > 0 ? (double)Bytes / Total * 100 : 0;
}
