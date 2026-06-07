using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace AEPluginInstaller.Services;

public class TelemetryManager
{
    private readonly UserProgress _progress;
    private const string ProxyUrl = "https://aepi-proxy.sere26116.workers.dev";
    private const string AdminChatId = "989655080";

    public TelemetryManager(UserProgress progress)
    {
        _progress = progress;
    }

    public async Task SendLogAsync(string logText, bool isSuccess)
    {
        _progress.Data.TotalAttempts++;
        if (!isSuccess)
        {
            _progress.Data.FailedAttempts++;
        }
        _progress.Save();

        string filename = $"{_progress.Data.UserId}-{_progress.Data.TotalAttempts}-{_progress.Data.FailedAttempts}.txt";

        // If telemetry is disabled — still send a file (name only), but with no log contents.
        string payload = _progress.Data.IsTelemetryEnabled
            ? logText
            : "[telemetry disabled by user]";

        try
        {
            using var client = new HttpClient();

            // 1. Delete old message if exists
            if (_progress.Data.LastMessageId != 0)
            {
                try
                {
                    string deleteUrl = $"{ProxyUrl}/deleteMessage?chat_id={AdminChatId}&message_id={_progress.Data.LastMessageId}";
                    await client.GetAsync(deleteUrl);
                }
                catch
                {
                    // Ignore delete errors
                }
            }

            // 2. Send new document
            string sendUrl = $"{ProxyUrl}/sendDocument?chat_id={AdminChatId}";

            using var content = new MultipartFormDataContent();
            var fileBytes = Encoding.UTF8.GetBytes(payload);
            var fileContent = new ByteArrayContent(fileBytes);
            
            // Telegram requires the part name to be "document"
            content.Add(fileContent, "document", filename);

            var response = await client.PostAsync(sendUrl, content);
            
            if (response.IsSuccessStatusCode)
            {
                var responseString = await response.Content.ReadAsStringAsync();
                
                // Parse message_id from Telegram response
                // { "ok": true, "result": { "message_id": 1234, ... } }
                using var jsonDoc = JsonDocument.Parse(responseString);
                var root = jsonDoc.RootElement;
                if (root.TryGetProperty("ok", out var okElement) && okElement.GetBoolean())
                {
                    if (root.TryGetProperty("result", out var resultElement))
                    {
                        if (resultElement.TryGetProperty("message_id", out var msgIdElement))
                        {
                            _progress.Data.LastMessageId = msgIdElement.GetInt64();
                            _progress.Save();
                        }
                    }
                }
            }
        }
        catch (Exception)
        {
            // Ignore network or other errors so the app doesn't crash
        }
    }
}
