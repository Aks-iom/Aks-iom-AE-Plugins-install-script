using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text.Json;

namespace AEPluginInstaller.Services.Install.Steps;

/// <summary>
/// JSON: <c>{"type":"extract_zip","source":"...","target":"..."}</c>.
/// Защита от Zip Slip: все имена нормализуются и проверяется, что они
/// после ресолва остаются внутри target.
/// </summary>
public class ExtractZipStep : IInstallStep
{
    public string Source { get; init; } = "";
    public string Target { get; init; } = "";

    public StepResult Execute(InstallContext ctx)
    {
        var arts = new List<Artifact>();
        try
        {
            var src = ctx.Expand(Source);
            var dst = ctx.Expand(Target);
            if (!File.Exists(src))
                return StepResult.Fail($"extract_zip: source not found: {src}", arts);

            var targetExisted = Directory.Exists(dst);
            Directory.CreateDirectory(dst);
            if (!targetExisted) arts.Add(Artifact.Dir(dst));

            var dstFull = Path.GetFullPath(dst);

            using var archive = ZipFile.OpenRead(src);

            // 1) zip-slip проверка
            foreach (var entry in archive.Entries)
            {
                var entryDst = Path.GetFullPath(Path.Combine(dst, entry.FullName));
                if (!entryDst.StartsWith(dstFull, StringComparison.OrdinalIgnoreCase))
                    return StepResult.Fail($"extract_zip: unsafe path in archive: {entry.FullName}", arts);
            }

            // 2) распаковка
            foreach (var entry in archive.Entries)
            {
                var entryDst = Path.Combine(dst, entry.FullName);
                if (string.IsNullOrEmpty(entry.Name)) // папка
                {
                    Directory.CreateDirectory(entryDst);
                    if (targetExisted) arts.Add(Artifact.Dir(entryDst));
                    continue;
                }
                Directory.CreateDirectory(Path.GetDirectoryName(entryDst)!);
                entry.ExtractToFile(entryDst, overwrite: true);
                arts.Add(Artifact.File(entryDst));
            }

            ctx.Log($"   ✓ Распакован архив → {dst}");
            return StepResult.Ok(arts);
        }
        catch (InvalidDataException ex)
        {
            return StepResult.Fail($"extract_zip: not a zip / corrupted: {ex.Message}", arts);
        }
        catch (Exception ex)
        {
            return StepResult.Fail($"extract_zip failed: {ex.Message}", arts);
        }
    }

    public class Factory : IInstallStepFactory
    {
        public string TypeName => "extract_zip";
        public IInstallStep Create(JsonElement node) => new ExtractZipStep
        {
            Source = node.GetProperty("source").GetString() ?? "",
            Target = node.GetProperty("target").GetString() ?? ""
        };
    }
}
