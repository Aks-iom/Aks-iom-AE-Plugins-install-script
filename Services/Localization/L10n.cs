using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows.Markup;

namespace AEPluginInstaller.Services.Localization;

/// <summary>
/// Простая локализация на JSON-словарях. Язык определяется один раз при старте:
/// настройка пользователя → авто по CultureInfo (ru/uk/be → ru, остальное → en).
/// </summary>
public static class L10n
{
    private static Dictionary<string, string> _strings = new();
    public static string Language { get; private set; } = "ru";

    public static void Initialize(string? userPreference)
    {
        string lang;
        if (userPreference is "ru" or "en")
            lang = userPreference;
        else
        {
            var sys = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName;
            lang = sys is "ru" or "uk" or "be" or "kk" ? "ru" : "en";
        }
        Load(lang);
    }

    public static void Load(string lang)
    {
        Language = lang;
        var fname = $"strings.{lang}.json";
        var path = Path.Combine(AppContext.BaseDirectory, "Resources", fname);
        try
        {
            if (File.Exists(path))
            {
                var json = File.ReadAllText(path);
                _strings = JsonSerializer.Deserialize<Dictionary<string, string>>(json)
                           ?? new Dictionary<string, string>();
            }
        }
        catch { _strings = new(); }
    }

    public static string T(string key, params object[] args)
    {
        if (!_strings.TryGetValue(key, out var s) || string.IsNullOrEmpty(s))
            return key;  // fallback — ключ виден в UI, легко найти потерянное
        try { return args.Length == 0 ? s : string.Format(s, args); }
        catch { return s; }
    }
}

/// <summary>Markup-extension для XAML: <c>{loc:T Key=plugins.title}</c>.</summary>
[MarkupExtensionReturnType(typeof(string))]
public class TExtension : MarkupExtension
{
    public string Key { get; set; } = "";
    public TExtension() { }
    public TExtension(string key) { Key = key; }
    public override object ProvideValue(IServiceProvider serviceProvider) => L10n.T(Key);
}
