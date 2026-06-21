using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace AEPluginInstaller.Services;

/// <summary>
/// Отправка детализированного session-лога в Telegram-бота (через прокси-воркер) как Document.
/// Счётчики TotalAttempts/FailedAttempts ведёт <see cref="SessionLog"/> — здесь только транспорт.
/// </summary>
public class TelemetryManager
{
    private readonly UserProgress _progress;
    private readonly SessionLog _sessionLog;
    private const string ProxyUrl = "https://aepi-proxy.sere26116.workers.dev";
    private const string AdminChatId = "989655080";

    public TelemetryManager(UserProgress progress, SessionLog sessionLog)
    {
        _progress = progress;
        _sessionLog = sessionLog;
    }

    /// <summary>
    /// Отправляет накопленный session-log как файл в Telegram.
    /// Имя файла — <c>{UserId}-{TotalAttempts}-{FailedAttempts}.txt</c>.
    /// Старое сообщение удаляется (если есть), новое сохраняется в LastMessageId.
    /// </summary>
    public async Task SendLogAsync()
    {
        var data = _progress.Data;
        string filename = $"{data.UserId}-{data.TotalAttempts}-{data.FailedAttempts}.txt";

        string payload = data.IsTelemetryEnabled
            ? _sessionLog.GetFullText()
            : "[telemetry disabled by user]";

        if (string.IsNullOrEmpty(payload))
            payload = "[empty]";

        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };

            // 1. Удалить старое сообщение (если было)
            if (data.LastMessageId != 0)
            {
                try
                {
                    var deleteUrl = $"{ProxyUrl}/deleteMessage?chat_id={AdminChatId}&message_id={data.LastMessageId}";
                    await client.GetAsync(deleteUrl);
                }
                catch
                {
                    // ignore — старое сообщение могли уже удалить вручную
                }
            }

            // 2. Отправить новый документ
            var sendUrl = $"{ProxyUrl}/sendDocument?chat_id={AdminChatId}";
            using var content = new MultipartFormDataContent();
            var fileBytes = Encoding.UTF8.GetBytes(payload);
            var fileContent = new ByteArrayContent(fileBytes);
            content.Add(fileContent, "document", filename);

            var response = await client.PostAsync(sendUrl, content);
            if (!response.IsSuccessStatusCode) return;

            var responseString = await response.Content.ReadAsStringAsync();
            using var jsonDoc = JsonDocument.Parse(responseString);
            var root = jsonDoc.RootElement;
            if (root.TryGetProperty("ok", out var okElement) && okElement.GetBoolean()
                && root.TryGetProperty("result", out var resultElement)
                && resultElement.TryGetProperty("message_id", out var msgIdElement))
            {
                data.LastMessageId = msgIdElement.GetInt64();
                _progress.Save();
            }
        }
        catch (Exception)
        {
            // Сетевые/прочие ошибки не валят установку
        }
    }
}
