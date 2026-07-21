import React from 'react';
import { ChevronDown, FolderOpen, RefreshCcw, Search, Upload, X } from 'lucide-react';
import { Button, Chip, EmptyState, InlineState, Modal, Panel, SectionHeader } from '../components/ui';
import { installSkillZip, loadSkillsSnapshot, readSkillReadme, toggleSkill, uninstallSkill } from '../api/adapters';
import { useAsync } from '../lib/useAsync';
import { shortenPaths } from '../lib/format';
import { usePreviewStore } from '../store/appStore';

// Known OpenClaw skills get a Chinese name + description so the card isn't a
// raw English npm id. Unknown skills are cleaned up (drop @scope/ and the
// openclaw- prefix) and fall back to their own description.
const SKILL_ALIASES: Record<string, { name: string; desc: string }> = {
  '@larksuite/openclaw-lark': { name: '飞书 / Lark 机器人', desc: '把自动化能力接入飞书消息通道：收发消息、推送任务结果。' },
  '@tencent-weixin/openclaw-weixin': { name: '微信机器人', desc: '把自动化能力接入微信消息通道：收发消息、推送结果。' },
};
const RUNTIME_LABELS: Record<string, string> = { external: '外部插件', node: 'Node 插件', python: 'Python 插件', builtin: '内置' };

function skillDisplay(skill: { id: string; name: string; description?: string }): { name: string; desc: string } {
  const alias = SKILL_ALIASES[skill.id] || SKILL_ALIASES[skill.name];
  if (alias) return alias;
  const cleaned = String(skill.name || skill.id)
    .replace(/^@[^/]+\//, '')
    .replace(/openclaw[-_]?/i, '')
    .replace(/[-_]/g, ' ')
    .trim();
  return { name: cleaned || skill.name || skill.id, desc: skill.description?.trim() || '暂无中文说明，可点「说明」查看。' };
}
function runtimeLabel(value: string): string {
  return RUNTIME_LABELS[value] || value;
}

function readAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('文件读取失败'));
    reader.readAsDataURL(file);
  });
}

export function SkillsPage() {
  const settings = usePreviewStore((state) => state.settings);
  const pushToast = usePreviewStore((state) => state.pushToast);
  const { data, loading, error, refresh } = useAsync(() => loadSkillsSnapshot(settings), [settings], { cacheKey: "skills" });
  const [query, setQuery] = React.useState('');
  const [readme, setReadme] = React.useState<{ title: string; path: string; content: string } | null>(null);
  const [busyId, setBusyId] = React.useState('');
  const filtered = (data?.skills || []).filter((skill) => {
    const text = `${skill.name} ${skill.description} ${skill.category} ${skill.runtime}`.toLowerCase();
    return text.includes(query.toLowerCase());
  });

  // Open an official skill library site in the system browser. Uses the shell
  // plugin in the desktop app (so it opens the real browser, not the app
  // webview) and falls back to window.open in the web preview.
  const handleOpenSite = async (url: string) => {
    try {
      const { open } = await import('@tauri-apps/plugin-shell');
      await open(url);
    } catch {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  };

  const handleUpload = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.zip,application/zip,application/x-zip-compressed';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      setBusyId('upload');
      try {
        const dataUrl = await readAsDataUrl(file);
        await installSkillZip(settings, file.name, dataUrl);
        pushToast({ tone: 'ok', title: 'Skill 已安装', detail: file.name });
        refresh();
      } catch (err) {
        pushToast({ tone: 'danger', title: '安装失败', detail: String(err) });
      } finally {
        setBusyId('');
      }
    };
    input.click();
  };

  const handleToggle = async (id: string, enabled: boolean) => {
    setBusyId(id);
    try {
      await toggleSkill(settings, id, enabled);
      pushToast({ tone: 'warn', title: enabled ? 'Skill 已启用' : 'Skill 已停用', detail: id });
      refresh();
    } catch (err) {
      pushToast({ tone: 'danger', title: '切换失败', detail: String(err) });
    } finally {
      setBusyId('');
    }
  };

  const handleReadme = async (id: string, title: string) => {
    setBusyId(id);
    try {
      const response = await readSkillReadme(settings, id);
      setReadme({ title, path: response.data?.path || '', content: response.data?.content || '' });
    } catch (err) {
      pushToast({ tone: 'danger', title: 'README 读取失败', detail: String(err) });
    } finally {
      setBusyId('');
    }
  };

  const handleRemove = async (id: string) => {
    setBusyId(id);
    try {
      await uninstallSkill(settings, id);
      pushToast({ tone: 'warn', title: 'Skill 已移除', detail: id });
      refresh();
    } catch (err) {
      pushToast({ tone: 'danger', title: '移除失败', detail: String(err) });
    } finally {
      setBusyId('');
    }
  };

  return (
    <div className="page-grid">
      <section className="hero-band">
        <div className="hero-copy">
          <div className="eyebrow">Skills 工作区</div>
          <h1>管理 OpenClaw 可以调用的能力模块。</h1>
          <p>安装、启用、查看说明或移除本地模块；每个操作都靠近对应 Skill。</p>
        </div>
        <div className="hero-actions">
          {data?.sites?.length === 1 ? (
            <Button variant="primary" icon={FolderOpen} onClick={() => handleOpenSite(data.sites[0].url)}>
              从官方库安装
            </Button>
          ) : (
            <Button variant="primary" icon={FolderOpen} onClick={() => document.getElementById('skill-sites-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
              从官方库安装
            </Button>
          )}
          <Button variant="quiet" icon={Upload} onClick={handleUpload} disabled={busyId === 'upload'}>安装 ZIP</Button>
          <Button variant="quiet" icon={RefreshCcw} onClick={refresh}>刷新</Button>
        </div>
      </section>

      <section className="content-grid content-grid-skills">
        <Panel className="surface-panel surface-panel-narrow">
          <SectionHeader eyebrow="筛选" title="查找模块" subtitle="搜索本地 Skills 工作区。" />
          <div className="search-row">
            <Search size={16} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 Skill、运行时或分类" />
          </div>
          <div className="detail-stack">
            <div className="detail-row"><span className="detail-label">状态文件</span><span className="detail-value" title={data?.statePath}>{shortenPaths(data?.statePath) || '暂无'}</span></div>
            <div className="detail-row"><span className="detail-label">目录</span><span className="detail-value">{data?.directories.length || 0}</span></div>
            <div className="detail-row"><span className="detail-label">站点</span><span className="detail-value">{data?.sites.length || 0}</span></div>
          </div>
          <div className="path-list">
            {data?.directories.map((dir) => (
              <div key={dir.key} className="path-card">
                <strong>{dir.label}</strong>
                <span title={dir.path}>{shortenPaths(dir.path)}</span>
                <Chip tone={dir.writable ? 'ok' : 'warn'}>{dir.writable ? '可写' : '只读'}</Chip>
              </div>
            ))}
          </div>
        </Panel>

        <Panel className="surface-panel">
          <SectionHeader eyebrow="已安装" title="可用 Skills" subtitle="启用、查看和移除操作直接放在每条记录旁边。" />
          {loading ? (
            <div className="panel-loading-inline">正在读取 Skills...</div>
          ) : error ? (
            <InlineState tone="danger" title="Skills 读取失败" description={error} />
          ) : filtered.length ? (
            <div className="skill-list">
              {filtered.map((skill) => (
                <div key={skill.id} className="skill-row">
                  <div className="skill-badge">{skill.icon}</div>
                  <div className="skill-copy">
                    <div className="skill-head">
                      <strong>{skillDisplay(skill).name}</strong>
                      <Chip tone={skill.enabled ? 'ok' : 'warn'}>{skill.enabled ? '已启用' : '已停用'}</Chip>
                    </div>
                    <div className="skill-meta">{skillDisplay(skill).desc}</div>
                    <details className="skill-details">
                      <summary>
                        <ChevronDown size={14} />
                        <span>详情</span>
                      </summary>
                      <div className="skill-meta">{skill.category} · {runtimeLabel(skill.runtime)} · v{skill.version}</div>
                      <div className="skill-meta" style={{ opacity: 0.55 }} title={`${skill.name}\n${skill.path}`}>{skill.name} · {shortenPaths(skill.path)}</div>
                    </details>
                  </div>
                  <div className="skill-actions">
                    <Button variant={skill.enabled ? 'danger' : 'success'} onClick={() => handleToggle(skill.id, !skill.enabled)} disabled={busyId === skill.id}>
                      {skill.enabled ? '停用' : '启用'}
                    </Button>
                    {skill.hasReadme ? <Button variant="quiet" onClick={() => handleReadme(skill.id, skill.name)} disabled={busyId === skill.id}>说明</Button> : null}
                    {skill.writable ? <Button variant="quiet" onClick={() => handleRemove(skill.id)} disabled={busyId === skill.id}>移除</Button> : null}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="暂无 Skills" description="安装一个 ZIP 后会出现在这里。" />
          )}
        </Panel>
      </section>

      <Panel className="surface-panel" id="skill-sites-panel">
        <SectionHeader eyebrow="官方库" title="Skill 站点" subtitle="点击「打开」前往官方库浏览并下载更多 Skill。" />
        <div className="site-grid">
          {data?.sites.map((site) => (
            <div key={site.url} className="site-card">
              <strong>{site.name}</strong>
              <span>{site.url}</span>
              <Button variant="primary" icon={FolderOpen} onClick={() => handleOpenSite(site.url)}>打开</Button>
            </div>
          ))}
        </div>
      </Panel>

      <Modal open={Boolean(readme)} title={readme?.title || '说明'} subtitle={readme?.path || ''} onClose={() => setReadme(null)} actions={<Button variant="secondary" onClick={() => setReadme(null)} icon={X}>关闭</Button>}>
        {readme ? <pre className="modal-pre">{readme.content}</pre> : null}
      </Modal>
    </div>
  );
}

