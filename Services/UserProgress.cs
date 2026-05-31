using System;
using System.IO;
using System.Text.Json;

namespace AEPluginInstaller.Services;

public class UserProgressData
{
    public string UserId { get; set; } = string.Empty;
    public int TotalAttempts { get; set; } = 0;
    public int FailedAttempts { get; set; } = 0;
    public long LastMessageId { get; set; } = 0;
    public bool IsTelemetryEnabled { get; set; } = true;
    public bool IsFirstLaunch { get; set; } = true;
}

public class UserProgress
{
    private readonly string _path;
    public UserProgressData Data { get; private set; } = new();

    public UserProgress()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "AEPluginInstaller", "cache");
        Directory.CreateDirectory(dir);
        _path = Path.Combine(dir, "user_telemetry.json");
        Load();
    }

    private void Load()
    {
        if (File.Exists(_path))
        {
            try
            {
                var content = File.ReadAllText(_path);
                Data = JsonSerializer.Deserialize<UserProgressData>(content) ?? new UserProgressData();
                return;
            }
            catch
            {
                // Fallback to new if corrupted
            }
        }
        
        // Initialize new
        Data = new UserProgressData
        {
            UserId = GenerateShortId(),
            IsFirstLaunch = true,
            IsTelemetryEnabled = true
        };
        Save();
    }

    public void Save()
    {
        try
        {
            var dir = Path.GetDirectoryName(_path);
            if (dir != null) Directory.CreateDirectory(dir);
            File.WriteAllText(_path, JsonSerializer.Serialize(Data, new JsonSerializerOptions { WriteIndented = true }));
        }
        catch { }
    }

    private string GenerateShortId()
    {
        // 8 char random id
        var chars = "abcdefghijklmnopqrstuvwxyz0123456789";
        var result = new char[8];
        var random = new Random();
        for (int i = 0; i < result.Length; i++)
        {
            result[i] = chars[random.Next(chars.Length)];
        }
        return new string(result);
    }
}
