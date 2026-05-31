using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace AEPluginInstaller.Services.Install.Steps;

/// <summary>
/// JSON: <c>{"type":"copy_file","source":"{SRC_DIR}/X.aex","target":"{PLUGINS_DIR}"}</c>.
/// Если target — папка, файл копируется внутрь с именем из source.
/// </summary>
public class CopyFileStep : IInstallStep
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
                return StepResult.Fail($"copy_file: source not found: {src}", arts);

            string finalPath, dstDir;
            if (dst.EndsWith('/') || dst.EndsWith('\\') || Directory.Exists(dst))
            {
                dstDir = dst;
                finalPath = Path.Combine(dstDir, Path.GetFileName(src));
            }
            else
            {
                dstDir = Path.GetDirectoryName(dst) ?? "";
                finalPath = dst;
            }

            var dirWasMissing = !string.IsNullOrEmpty(dstDir) && !Directory.Exists(dstDir);
            if (!string.IsNullOrEmpty(dstDir))
                Directory.CreateDirectory(dstDir);
            if (dirWasMissing)
                arts.Add(Artifact.Dir(dstDir));

            File.Copy(src, finalPath, overwrite: true);
            arts.Add(Artifact.File(finalPath));

            ctx.Log($"   ✓ Скопирован файл → {finalPath}");
            return StepResult.Ok(arts);
        }
        catch (Exception ex)
        {
            return StepResult.Fail($"copy_file failed: {ex.Message}", arts);
        }
    }

    public class Factory : IInstallStepFactory
    {
        public string TypeName => "copy_file";
        public IInstallStep Create(JsonElement node) => new CopyFileStep
        {
            Source = node.GetProperty("source").GetString() ?? "",
            Target = node.GetProperty("target").GetString() ?? ""
        };
    }
}
