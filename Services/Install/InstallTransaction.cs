using System;
using System.Collections.Generic;
using System.IO;

namespace AEPluginInstaller.Services.Install;

/// <summary>
/// Накапливает артефакты выполненных шагов и откатывает их при ошибке.
/// Защищает от потери пользовательских данных через pending-backups:
/// шаги, которые делают бэкап целевой папки (CopyDir replace), регистрируют
/// его здесь. Бэкап удаляется ТОЛЬКО при <see cref="Commit"/>;
/// при <see cref="Rollback"/> бэкап восстанавливается на место.
/// </summary>
public class InstallTransaction : IDisposable
{
    private readonly InstallContext _ctx;
    private readonly List<Artifact> _artifacts = new();
    private readonly Dictionary<string, string> _pendingBackups = new();
    private bool _committed;
    private bool _rolledBack;

    public InstallTransaction(InstallContext ctx) { _ctx = ctx; }

    public IReadOnlyList<Artifact> Artifacts => _artifacts;

    public void AddArtifacts(IEnumerable<Artifact> arts)
    {
        if (arts == null) return;
        _artifacts.AddRange(arts);
    }

    /// <summary>Регистрирует бэкап для отложенного удаления/восстановления.</summary>
    public void RegisterBackup(string targetPath, string backupPath)
    {
        if (!string.IsNullOrEmpty(targetPath) && !string.IsNullOrEmpty(backupPath))
            _pendingBackups[targetPath] = backupPath;
    }

    public void Commit()
    {
        _committed = true;
        foreach (var (_, backup) in _pendingBackups)
        {
            if (Directory.Exists(backup))
            {
                try { Directory.Delete(backup, recursive: true); } catch { }
            }
        }
        _pendingBackups.Clear();
    }

    public void Rollback()
    {
        if (_rolledBack) return;
        _rolledBack = true;

        if (_artifacts.Count == 0 && _pendingBackups.Count == 0) return;

        _ctx.Log("[!] Откат: удаление частично установленных файлов...");

        var warnedExe = false;
        // в обратном порядке — сначала созданное последним
        for (int i = _artifacts.Count - 1; i >= 0; i--)
        {
            var art = _artifacts[i];
            if (art.Type == ArtifactType.ExeInstall)
            {
                if (!warnedExe)
                {
                    _ctx.Log($"⚠ '{art.Path}' установлен через .exe-инсталлер. " +
                             $"Удалите его вручную через «Программы и компоненты», если нужно.");
                    warnedExe = true;
                }
                continue;
            }
            try { ArtifactRemover.Remove(art, ignoreErrors: true); }
            catch (Exception ex) { _ctx.Log($"   Не удалось откатить {art.Path}: {ex.Message}"); }
        }

        // Восстановление бэкапов
        foreach (var (target, backup) in _pendingBackups)
        {
            if (string.IsNullOrEmpty(backup) || !Directory.Exists(backup)) continue;
            try
            {
                if (Directory.Exists(target)) Directory.Delete(target, recursive: true);
                Directory.Move(backup, target);
                _ctx.Log($"   ↶ Восстановлен оригинал из бэкапа: {target}");
            }
            catch (Exception ex)
            {
                _ctx.Log($"   ! Не удалось восстановить бэкап {backup} → {target}: {ex.Message}");
            }
        }
        _pendingBackups.Clear();
    }

    public void Dispose()
    {
        if (!_committed && !_rolledBack)
            Rollback();
    }
}
