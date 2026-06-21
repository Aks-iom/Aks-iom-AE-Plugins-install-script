using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Http;
using System.Net.Security;
using System.Security.Authentication;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace AEPluginInstaller.Services.Updater;

/// <summary>
/// Портативный авто-апдейтер: проверка JSON-манифеста на GitHub Raw, скачивание,
/// самообновление через .bat в %TEMP%. UI здесь нет — слой представления вызывает
/// <see cref="CheckAsync"/> и сам решает, что показывать.
/// </summary>
public sealed class PortableAutoUpdater
{
    private const string ManifestUrl =
        "https://raw.githubusercontent.com/Aks-iom/aksiom-installer-data/main/update.json";

    private const string UserAgent = "AEPluginInstaller-Updater";
    private const string ConfigFileName = "updater_config.json";

    private static readonly HttpClient Http = CreateHttpClient();

    // --- Состояние: блокировка во время установки плагинов ----------------
    private int _installationRunning;

    /// <summary>true, пока хотя бы один сценарий установки активен.</summary>
    public bool IsInstallationRunning => Volatile.Read(ref _installationRunning) > 0;

    /// <summary>Пометить начало установки. Вызовы можно вкладывать.</summary>
    public void BeginInstallation() => Interlocked.Increment(ref _installationRunning);

    /// <summary>Пометить завершение установки.</summary>
    public void EndInstallation()
    {
        if (Interlocked.Decrement(ref _installationRunning) < 0)
            Interlocked.Exchange(ref _installationRunning, 0);
    }

    // --- Основной API -----------------------------------------------------

    public sealed record UpdateInfo(Version NewVersion, string DownloadUrl);

    /// <summary>
    /// Проверить наличие обновления. Возвращает null, если обновляться не нужно
    /// (нет новой версии, версия в игноре, идёт установка, ошибка сети и т.п.).
    /// </summary>
    /// <summary>Результат ручной проверки — для UI настроек.</summary>
    public enum ManualCheckOutcome { UpdateAvailable, UpToDate, NetworkError }

    public sealed record ManualCheckResult(ManualCheckOutcome Outcome, UpdateInfo? Info);

    public Task<UpdateInfo?> CheckAsync(CancellationToken ct = default)
        => CheckAsync(force: false, ct);

    /// <summary>
    /// Проверить наличие обновления. Возвращает null, если обновляться не нужно
    /// (нет новой версии, версия в игноре, идёт установка, ошибка сети и т.п.).
    /// При <paramref name="force"/>=true игнорирует "IgnoreVersion" из конфига —
    /// для кнопки «Проверить обновления» в настройках.
    /// </summary>
    public async Task<UpdateInfo?> CheckAsync(bool force, CancellationToken ct = default)
    {
        if (IsInstallationRunning) return null;

        try
        {
            var current = GetCurrentVersion();
            var manifest = await FetchManifestAsync(ct).ConfigureAwait(false);
            if (manifest is null) return null;

            if (!Version.TryParse(manifest.Version, out var remote)) return null;
            if (remote <= current) return null;

            if (!force)
            {
                var cfg = ReadConfig();
                if (cfg.IgnoreVersion is not null
                    && Version.TryParse(cfg.IgnoreVersion, out var ignored)
                    && ignored >= remote)
                {
                    return null;
                }
            }

            if (string.IsNullOrWhiteSpace(manifest.DownloadUrl)) return null;
            return new UpdateInfo(remote, manifest.DownloadUrl!);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Ручная проверка из настроек. В отличие от <see cref="CheckAsync(CancellationToken)"/>
    /// различает «нет обновлений» и «нет связи».
    /// </summary>
    public async Task<ManualCheckResult> CheckManuallyAsync(CancellationToken ct = default)
    {
        try
        {
            var current  = GetCurrentVersion();
            var manifest = await FetchManifestAsync(ct).ConfigureAwait(false);
            if (manifest is null) return new ManualCheckResult(ManualCheckOutcome.NetworkError, null);

            if (!Version.TryParse(manifest.Version, out var remote)
                || string.IsNullOrWhiteSpace(manifest.DownloadUrl))
            {
                return new ManualCheckResult(ManualCheckOutcome.NetworkError, null);
            }

            if (remote <= current)
                return new ManualCheckResult(ManualCheckOutcome.UpToDate, null);

            return new ManualCheckResult(
                ManualCheckOutcome.UpdateAvailable,
                new UpdateInfo(remote, manifest.DownloadUrl!));
        }
        catch
        {
            return new ManualCheckResult(ManualCheckOutcome.NetworkError, null);
        }
    }

    /// <summary>Сохранить выбор «не предлагать эту версию».</summary>
    public void IgnoreVersion(Version version)
    {
        try
        {
            var cfg = ReadConfig();
            cfg.IgnoreVersion = version.ToString();
            WriteConfig(cfg);
        }
        catch { }
    }

    /// <summary>Прогресс скачивания: (получено, всего или null если не известно).</summary>
    public sealed record DownloadProgress(long BytesReceived, long? TotalBytes);

    /// <summary>
    /// Скачивает новый exe (или достаёт .exe из zip) в %TEMP%, пишет updater.ps1 рядом,
    /// запускает PowerShell скрыто (он сам поднимает стилизованное WPF-окно ожидания)
    /// и завершает текущий процесс.
    /// </summary>
    public async Task StartUpdateAndExitAsync(
        UpdateInfo info,
        IProgress<DownloadProgress>? progress = null,
        CancellationToken ct = default)
    {
        var currentExe = GetCurrentExePath();

        // Изолированная подпапка в %TEMP% на каждую сессию обновления —
        // чтобы рядом с .exe ничего лишнего не появлялось.
        var stageDir = Path.Combine(
            Path.GetTempPath(),
            "AEPluginInstaller_Updater",
            Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(stageDir);

        var downloadTmp = Path.Combine(stageDir, "download.bin");
        var newExePath  = Path.Combine(stageDir, "new.exe");

        await DownloadAsync(info.DownloadUrl, downloadTmp, progress, ct).ConfigureAwait(false);

        if (IsZip(downloadTmp))
        {
            var extracted = ExtractSingleExeFromZip(downloadTmp, stageDir);
            try { File.Delete(downloadTmp); } catch { }
            File.Move(extracted, newExePath, overwrite: true);
        }
        else
        {
            File.Move(downloadTmp, newExePath, overwrite: true);
        }

        var ps1Path = WriteUpdaterPs1(stageDir, currentExe, newExePath);
        LaunchPowerShellHidden(ps1Path, currentExe, newExePath, stageDir);

        // Дать PowerShell время поднять WPF-окно поверх — чтобы пользователь
        // не увидел «дыру» между закрытием нашего окна и появлением окна апдейтера.
        await Task.Delay(400, ct).ConfigureAwait(false);

        Environment.Exit(0);
    }

    // --- Внутренние шаги --------------------------------------------------

    private static HttpClient CreateHttpClient()
    {
        // SocketsHttpHandler с явным выбором TLS-протоколов: видели случаи, когда
        // редирект с raw.githubusercontent.com → objects.githubusercontent.com падал
        // с "The SSL connection could not be established" (отсечённый TLS 1.3, кривой
        // системный набор протоколов и т. п.). Включаем 1.2 + 1.3 явно.
        var handler = new SocketsHttpHandler
        {
            AllowAutoRedirect            = true,
            AutomaticDecompression       = DecompressionMethods.GZip | DecompressionMethods.Deflate,
            ConnectTimeout               = TimeSpan.FromSeconds(20),
            PooledConnectionLifetime     = TimeSpan.FromMinutes(5),
            SslOptions = new SslClientAuthenticationOptions
            {
                EnabledSslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13,
            },
        };

        // Общий таймаут отключён: HttpClient.Timeout распространяется и на чтение
        // тела ответа, что для многомегабайтного exe на медленных каналах не годится.
        // Таймауты ставим точечно через CancellationToken (для манифеста).
        var h = new HttpClient(handler)
        {
            Timeout = Timeout.InfiniteTimeSpan
        };
        h.DefaultRequestHeaders.UserAgent.ParseAdd(UserAgent);
        h.DefaultRequestHeaders.CacheControl = new System.Net.Http.Headers.CacheControlHeaderValue
        {
            NoCache = true
        };
        return h;
    }

    private sealed class Manifest
    {
        [JsonPropertyName("version")]     public string? Version     { get; set; }
        [JsonPropertyName("downloadUrl")] public string? DownloadUrl { get; set; }
    }

    private static async Task<Manifest?> FetchManifestAsync(CancellationToken ct)
    {
        // Защита от кеша CDN.
        var url = ManifestUrl + (ManifestUrl.Contains('?') ? "&" : "?") + "ts=" + DateTime.UtcNow.Ticks;

        // 1) Основной путь — HttpClient (TLS 1.2/1.3, авторедирект, gzip).
        try
        {
            using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeoutCts.CancelAfter(TimeSpan.FromSeconds(20));

            using var resp = await Http.GetAsync(url, timeoutCts.Token).ConfigureAwait(false);
            if (!resp.IsSuccessStatusCode) return null;
            await using var stream = await resp.Content.ReadAsStreamAsync(timeoutCts.Token).ConfigureAwait(false);
            return await JsonSerializer.DeserializeAsync<Manifest>(stream, cancellationToken: timeoutCts.Token)
                                       .ConfigureAwait(false);
        }
        catch (Exception ex) when (IsTransportError(ex))
        {
            // 2) Фолбэк — встроенный curl.exe (Win10 1803+ / Win11). У него своя TLS-реализация
            //    и доступ к системному сертификат-стору; часто проходит там, где SChannel в .NET
            //    падает (битый набор протоколов, корпоративный MITM-AV и т. п.).
            var json = await TryCurlGetStringAsync(url, ct).ConfigureAwait(false);
            if (string.IsNullOrEmpty(json)) return null;
            try { return JsonSerializer.Deserialize<Manifest>(json); }
            catch { return null; }
        }
    }

    private static bool IsTransportError(Exception ex)
    {
        for (var e = ex; e != null; e = e.InnerException)
        {
            if (e is HttpRequestException
                || e is System.Net.Sockets.SocketException
                || e is System.Security.Authentication.AuthenticationException
                || e is IOException) return true;
            var m = e.Message ?? "";
            if (m.Contains("SSL", StringComparison.OrdinalIgnoreCase)
                || m.Contains("TLS", StringComparison.OrdinalIgnoreCase)) return true;
        }
        return false;
    }

    private static string? FindCurl()
    {
        var sys = Path.Combine(Environment.SystemDirectory, "curl.exe");
        if (File.Exists(sys)) return sys;
        // На редких сборках Windows curl лежит только в PATH.
        var paths = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var p in paths.Split(';', StringSplitOptions.RemoveEmptyEntries))
        {
            try
            {
                var c = Path.Combine(p.Trim(), "curl.exe");
                if (File.Exists(c)) return c;
            }
            catch { }
        }
        return null;
    }

    private static async Task<string?> TryCurlGetStringAsync(string url, CancellationToken ct)
    {
        var curl = FindCurl();
        if (curl is null) return null;
        var tmp = Path.Combine(Path.GetTempPath(), "aepi_manifest_" + Guid.NewGuid().ToString("N") + ".json");
        try
        {
            var ok = await RunCurlAsync(curl,
                $"-fsSL --tlsv1.2 --max-time 20 -A \"{UserAgent}\" -o \"{tmp}\" \"{url}\"",
                progress: null, ct).ConfigureAwait(false);
            if (!ok || !File.Exists(tmp)) return null;
            return await File.ReadAllTextAsync(tmp, ct).ConfigureAwait(false);
        }
        finally
        {
            try { if (File.Exists(tmp)) File.Delete(tmp); } catch { }
        }
    }

    private static async Task DownloadAsync(
        string url,
        string destination,
        IProgress<DownloadProgress>? progress,
        CancellationToken ct)
    {
        try
        {
            await DownloadViaHttpClientAsync(url, destination, progress, ct).ConfigureAwait(false);
        }
        catch (Exception ex) when (IsTransportError(ex))
        {
            // Чистим частично закачанное и пробуем curl.exe.
            try { if (File.Exists(destination)) File.Delete(destination); } catch { }
            var curl = FindCurl();
            if (curl is null) throw;  // Фолбэк недоступен → пусть наверх летит исходная ошибка.
            var args = $"-fsSL --tlsv1.2 -A \"{UserAgent}\" -o \"{destination}\" \"{url}\"";
            var ok = await RunCurlAsync(curl, args, progress, ct).ConfigureAwait(false);
            if (!ok || !File.Exists(destination) || new FileInfo(destination).Length == 0)
                throw new HttpRequestException("curl fallback failed");
        }
    }

    private static async Task DownloadViaHttpClientAsync(
        string url,
        string destination,
        IProgress<DownloadProgress>? progress,
        CancellationToken ct)
    {
        using var resp = await Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, ct)
                                   .ConfigureAwait(false);
        resp.EnsureSuccessStatusCode();

        long? total = resp.Content.Headers.ContentLength;
        await using var inStream  = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        await using var outStream = new FileStream(destination, FileMode.Create, FileAccess.Write,
                                                   FileShare.None, 81920, useAsync: true);

        var buffer = new byte[81920];
        long received = 0;
        progress?.Report(new DownloadProgress(0, total));
        DateTime lastReport = DateTime.UtcNow;

        int read;
        while ((read = await inStream.ReadAsync(buffer, ct).ConfigureAwait(false)) > 0)
        {
            await outStream.WriteAsync(buffer.AsMemory(0, read), ct).ConfigureAwait(false);
            received += read;
            // Отправляем не чаще ~30 раз/сек, чтобы не флудить UI-поток.
            var now = DateTime.UtcNow;
            if ((now - lastReport).TotalMilliseconds >= 33)
            {
                progress?.Report(new DownloadProgress(received, total));
                lastReport = now;
            }
        }
        progress?.Report(new DownloadProgress(received, total));
    }

    /// <summary>
    /// Запускает curl с прогресс-баром, парсит его stderr-строки вида
    /// "  3 17.4M    3  617k    0 ..." и репортит в IProgress.
    /// </summary>
    private static async Task<bool> RunCurlAsync(
        string curlPath,
        string arguments,
        IProgress<DownloadProgress>? progress,
        CancellationToken ct)
    {
        var psi = new ProcessStartInfo
        {
            FileName               = curlPath,
            Arguments              = arguments,
            CreateNoWindow         = true,
            UseShellExecute        = false,
            RedirectStandardError  = true,
            RedirectStandardOutput = true,
        };

        using var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
        if (!proc.Start()) return false;

        // curl шлёт progress bar в stderr; читаем по символьно, парсим суммарную строку.
        var stderrTask = Task.Run(async () =>
        {
            var buf = new char[256];
            var line = new StringBuilder();
            DateTime last = DateTime.UtcNow;
            while (true)
            {
                int n = await proc.StandardError.ReadAsync(buf, 0, buf.Length).ConfigureAwait(false);
                if (n <= 0) break;
                for (int i = 0; i < n; i++)
                {
                    var ch = buf[i];
                    if (ch is '\r' or '\n')
                    {
                        ParseCurlProgress(line.ToString(), progress, ref last);
                        line.Clear();
                    }
                    else line.Append(ch);
                }
            }
        }, ct);

        try
        {
            await proc.WaitForExitAsync(ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            try { proc.Kill(true); } catch { }
            throw;
        }

        try { await stderrTask.ConfigureAwait(false); } catch { }
        return proc.ExitCode == 0;
    }

    private static void ParseCurlProgress(string line, IProgress<DownloadProgress>? progress, ref DateTime last)
    {
        if (progress is null || string.IsNullOrWhiteSpace(line)) return;
        // Шапка вида "  % Total ..." — пропускаем.
        if (line.TrimStart().StartsWith("%", StringComparison.Ordinal)) return;

        // Колонки: % Total / Total / % Received / Received / ...
        var parts = line.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 4) return;

        long total    = ParseCurlSize(parts[1]);
        long received = ParseCurlSize(parts[3]);
        if (received <= 0) return;

        var now = DateTime.UtcNow;
        if ((now - last).TotalMilliseconds < 33) return;
        last = now;
        progress.Report(new DownloadProgress(received, total > 0 ? total : null));
    }

    private static long ParseCurlSize(string s)
    {
        if (string.IsNullOrEmpty(s) || s == "--") return 0;
        double mul = 1;
        var tail = s[^1];
        if (char.IsLetter(tail))
        {
            mul = tail switch { 'k' or 'K' => 1024.0,
                                'M' => 1024.0 * 1024,
                                'G' => 1024.0 * 1024 * 1024,
                                _ => 1 };
            s = s[..^1];
        }
        return double.TryParse(s, System.Globalization.NumberStyles.Any,
                               System.Globalization.CultureInfo.InvariantCulture, out var d)
               ? (long)(d * mul) : 0;
    }

    private static bool IsZip(string path)
    {
        try
        {
            using var fs = File.OpenRead(path);
            Span<byte> buf = stackalloc byte[4];
            if (fs.Read(buf) < 4) return false;
            return buf[0] == 0x50 && buf[1] == 0x4B && buf[2] == 0x03 && buf[3] == 0x04;
        }
        catch { return false; }
    }

    private static string ExtractSingleExeFromZip(string zipPath, string targetDir)
    {
        using var archive = ZipFile.OpenRead(zipPath);
        ZipArchiveEntry? exe = null;
        foreach (var entry in archive.Entries)
        {
            if (entry.FullName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
            {
                exe = entry;
                break;
            }
        }
        if (exe is null) throw new InvalidDataException("В архиве не найден .exe");

        var outPath = Path.Combine(targetDir, "_extracted_" + Guid.NewGuid().ToString("N") + ".exe");
        exe.ExtractToFile(outPath, overwrite: true);
        return outPath;
    }

    // --- Версия / пути ----------------------------------------------------

    private static Version GetCurrentVersion()
    {
        var path = GetCurrentExePath();
        var info = FileVersionInfo.GetVersionInfo(path);
        var s = info.FileVersion ?? info.ProductVersion ?? "0.0.0.0";
        return Version.TryParse(s, out var v) ? v : new Version(0, 0, 0, 0);
    }

    private static string GetCurrentExePath()
    {
        // Для PublishSingleFile корректнее всего — MainModule.FileName.
        var p = Process.GetCurrentProcess().MainModule?.FileName;
        if (!string.IsNullOrEmpty(p)) return p!;
        return Environment.ProcessPath ?? AppContext.BaseDirectory;
    }

    // --- Config рядом с exe (Hidden + System) -----------------------------

    private sealed class UpdaterConfig
    {
        [JsonPropertyName("IgnoreVersion")] public string? IgnoreVersion { get; set; }
    }

    private static string ConfigPath =>
        Path.Combine(Path.GetDirectoryName(GetCurrentExePath())!, ConfigFileName);

    private static UpdaterConfig ReadConfig()
    {
        try
        {
            if (!File.Exists(ConfigPath)) return new UpdaterConfig();
            return JsonSerializer.Deserialize<UpdaterConfig>(File.ReadAllText(ConfigPath))
                   ?? new UpdaterConfig();
        }
        catch { return new UpdaterConfig(); }
    }

    private static void WriteConfig(UpdaterConfig cfg)
    {
        var json = JsonSerializer.Serialize(cfg, new JsonSerializerOptions { WriteIndented = true });
        if (File.Exists(ConfigPath))
        {
            try { File.SetAttributes(ConfigPath, FileAttributes.Normal); } catch { }
        }
        File.WriteAllText(ConfigPath, json);
        // Скрытый+системный — по правилу "только .exe на виду".
        try
        {
            File.SetAttributes(ConfigPath, FileAttributes.Hidden | FileAttributes.System);
        }
        catch { }
    }

    // --- PowerShell-скрипт самообновления с WPF-окном ---------------------

    /// <summary>
    /// Пишет updater.ps1 в %TEMP%-папку обновления. Скрипт поднимает стилизованное
    /// WPF-окно (никаких чёрных консолей), ждёт закрытия старого процесса,
    /// заменяет .exe, запускает новый, чистит %TEMP%.
    /// </summary>
    private static string WriteUpdaterPs1(string stageDir, string oldExe, string newExe)
    {
        var ps1Path = Path.Combine(stageDir, "updater.ps1");
        var pid     = Environment.ProcessId;
        var appName = Path.GetFileNameWithoutExtension(oldExe);

        // Эскейп для подстановки в одиночных кавычках PS: ' → ''
        static string PS(string s) => s.Replace("'", "''");

        var script = $@"
# updater.ps1 — генерируется AEPluginInstaller. Поднимает скрытое WPF-окно,
# ждёт завершения старого процесса, заменяет .exe из %TEMP%, перезапускает.

$ErrorActionPreference = 'Stop'

$oldExe   = '{PS(oldExe)}'
$newExe   = '{PS(newExe)}'
$stageDir = '{PS(stageDir)}'
$oldPid   = {pid}
$appName  = '{PS(appName)}'
$logPath  = Join-Path (Split-Path $stageDir -Parent) 'last-error.log'

try {{
  Add-Type -AssemblyName PresentationFramework
  Add-Type -AssemblyName PresentationCore
  Add-Type -AssemblyName WindowsBase

  $xaml = @'
<Window xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
        xmlns:x=""http://schemas.microsoft.com/winfx/2006/xaml""
        Title=""AE Plugin Installer""
        Width=""460"" Height=""180""
        WindowStartupLocation=""CenterScreen""
        ResizeMode=""NoResize""
        WindowStyle=""None""
        AllowsTransparency=""False""
        ShowInTaskbar=""True""
        Topmost=""True""
        Background=""#1E1F22"">
  <Border BorderBrush=""#3A3A40"" BorderThickness=""1"">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height=""34""/>
        <RowDefinition Height=""*""/>
      </Grid.RowDefinitions>

      <!-- Своя тёмная шапка (без логотипа PowerShell) -->
      <Grid Grid.Row=""0"" x:Name=""TitleBar"" Background=""#1E1F22"">
        <StackPanel Orientation=""Horizontal"" VerticalAlignment=""Center"" Margin=""12,0,0,0"">
          <TextBlock Text=""⬆"" FontSize=""13"" Foreground=""#7C5CFF""
                     VerticalAlignment=""Center"" Margin=""0,0,8,0""/>
          <TextBlock Text=""AE Plugin Installer"" FontSize=""12""
                     Foreground=""#C8C8C8"" VerticalAlignment=""Center""/>
        </StackPanel>
      </Grid>

      <!-- Контент -->
      <Grid Grid.Row=""1"" Margin=""24,14,24,18"">
        <Grid.RowDefinitions>
          <RowDefinition Height=""Auto""/>
          <RowDefinition Height=""Auto""/>
          <RowDefinition Height=""Auto""/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row=""0"" x:Name=""HeaderText""
                   Text=""Установка обновления""
                   FontSize=""16"" FontWeight=""Bold""
                   Foreground=""#F0F0F0""
                   Margin=""0,0,0,8""/>

        <TextBlock Grid.Row=""1"" x:Name=""StatusText""
                   Text=""Подготовка...""
                   FontSize=""13"" Foreground=""#C8C8C8""
                   TextWrapping=""Wrap"" Margin=""0,0,0,18""/>

        <!-- Свой прогресс-бар: тёмный трек + плавно бегущая ""гусеница"" -->
        <Border Grid.Row=""2"" Background=""#2A2C30"" CornerRadius=""4"" Height=""8""
                ClipToBounds=""True"">
          <Border x:Name=""BarFill"" Width=""140"" Background=""#7C5CFF""
                  CornerRadius=""4"" HorizontalAlignment=""Left"">
            <Border.RenderTransform>
              <TranslateTransform x:Name=""BarTransform""/>
            </Border.RenderTransform>
          </Border>
        </Border>
      </Grid>
    </Grid>
  </Border>
</Window>
'@

  [xml]$xml = $xaml
  $reader   = New-Object System.Xml.XmlNodeReader $xml
  $window   = [Windows.Markup.XamlReader]::Load($reader)
  $status   = $window.FindName('StatusText')
  $header   = $window.FindName('HeaderText')
  $titleBar = $window.FindName('TitleBar')
  $barFill  = $window.FindName('BarFill')
  $barTr    = $window.FindName('BarTransform')

  # Перетаскивание окна за свою шапку (раз стандартного title bar нет).
  $titleBar.Add_MouseLeftButtonDown({{ try {{ $window.DragMove() }} catch {{ }} }})

  # Плавная индетерминатная анимация ""гусеницы"".
  $window.Add_Loaded({{
    $anim = New-Object System.Windows.Media.Animation.DoubleAnimation
    $anim.From = -150
    $anim.To   = 420
    $anim.Duration = [System.Windows.Duration]::new([TimeSpan]::FromSeconds(1.4))
    $anim.RepeatBehavior = [System.Windows.Media.Animation.RepeatBehavior]::Forever
    $barTr.BeginAnimation([System.Windows.Media.TranslateTransform]::XProperty, $anim)
  }})

  # Машина состояний на DispatcherTimer. Сырой .NET-поток + scriptblock не
  # годится: ScriptBlock.Invoke() требует PS-runspace, а на чужой OS-thread
  # его нет — командлеты (Get-Process / Move-Item / Start-Process) и вызовы
  # вложенных скриптблоков (& $setUi) тихо падают, и установка обрывается.
  # Tick DispatcherTimer'а проходит через PS event bridge → runspace есть,
  # а UI не блокируется: анимация ""гусеницы"" продолжает крутиться.
  $state = [pscustomobject]@{{
    Phase        = 'wait'
    Deadline     = (Get-Date).AddSeconds(30)
    MoveAttempts = 0
    ErrorTicks   = 0
  }}

  $timer = New-Object System.Windows.Threading.DispatcherTimer
  $timer.Interval = [TimeSpan]::FromMilliseconds(300)
  $timer.Add_Tick({{
    try {{
      switch ($state.Phase) {{
        'wait' {{
          $p = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
          if (-not $p -or (Get-Date) -gt $state.Deadline) {{
            $state.Phase = 'move'
            $status.Text = ""Установка $appName...""
            $header.Text = 'Установка обновления'
          }}
        }}
        'move' {{
          try {{
            if (Test-Path -LiteralPath $oldExe) {{
              Remove-Item -LiteralPath $oldExe -Force -ErrorAction Stop
            }}
            Move-Item -LiteralPath $newExe -Destination $oldExe -Force -ErrorAction Stop
            $state.Phase = 'launch'
            $status.Text = 'Перезапуск...'
          }} catch {{
            $state.MoveAttempts++
            if ($state.MoveAttempts -ge 12) {{
              try {{ Add-Content -LiteralPath $logPath -Value (""[move] "" + $_.Exception.ToString()) }} catch {{ }}
              $status.Text = 'Не удалось заменить файл. Закройте окно и попробуйте позже.'
              $header.Text = 'Ошибка обновления'
              $state.Phase = 'error'
            }}
          }}
        }}
        'launch' {{
          $workDir = Split-Path -Parent $oldExe
          $started = $false
          try {{
            Start-Process -FilePath $oldExe -WorkingDirectory $workDir -ErrorAction Stop | Out-Null
            $started = $true
          }} catch {{ }}
          if (-not $started) {{
            try {{
              $psi = New-Object System.Diagnostics.ProcessStartInfo
              $psi.FileName = $oldExe
              $psi.WorkingDirectory = $workDir
              $psi.UseShellExecute = $true
              [System.Diagnostics.Process]::Start($psi) | Out-Null
              $started = $true
            }} catch {{
              try {{ Add-Content -LiteralPath $logPath -Value (""[restart] "" + $_.Exception.ToString()) }} catch {{ }}
            }}
          }}
          $timer.Stop()
          $window.Close()
        }}
        'error' {{
          $state.ErrorTicks++
          if ($state.ErrorTicks -ge 20) {{
            $timer.Stop()
            $window.Close()
          }}
        }}
      }}
    }} catch {{
      try {{ Add-Content -LiteralPath $logPath -Value (""[tick] "" + $_.Exception.ToString()) }} catch {{ }}
      try {{ $timer.Stop() }} catch {{ }}
      try {{ $window.Close() }} catch {{ }}
    }}
  }})

  $window.Add_ContentRendered({{
    $status.Text = 'Ожидание закрытия программы...'
    $timer.Start()
  }})

  # Чистим %TEMP%-stage после закрытия окна.
  $window.Add_Closed({{
    try {{
      [System.Threading.Thread]::Sleep(200)
      Remove-Item -LiteralPath $stageDir -Recurse -Force -ErrorAction SilentlyContinue
    }} catch {{ }}
  }})

  [void]$window.ShowDialog()
}}
catch {{
  # Если упали ДО показа окна — оставим след для диагностики.
  try {{ Add-Content -LiteralPath $logPath -Value (""[top] "" + $_.Exception.ToString()) }} catch {{ }}
}}
";

        File.WriteAllText(ps1Path, script, new UTF8Encoding(true));
        return ps1Path;
    }

    private static void LaunchPowerShellHidden(string ps1Path, string oldExe, string newExe, string stageDir)
    {
        // -WindowStyle Hidden + CreateNoWindow=true — никакой чёрной консоли
        // даже на долю секунды. WPF-окно поднимается из самого скрипта.
        var psi = new ProcessStartInfo
        {
            FileName        = "powershell.exe",
            Arguments       =
                "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -STA " +
                $"-File \"{ps1Path}\"",
            CreateNoWindow  = true,
            UseShellExecute = false,
            WindowStyle     = ProcessWindowStyle.Hidden,
            WorkingDirectory = stageDir
        };
        Process.Start(psi);
    }
}
