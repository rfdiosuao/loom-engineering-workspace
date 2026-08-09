import React from 'react';
import {
  ArrowRight,
  BookOpen,
  Cloud,
  Download,
  History,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Smartphone,
  Trash2,
  Upload,
  Zap,
} from 'lucide-react';

import {
  acquisitionApi,
  parseErrorText,
  skillsApi,
  type AcquisitionTemplateSummary,
  type AcquisitionTemplateStatus,
  type SkillListResponse,
  type SkillSummary,
} from '../../services/api';
import { useAppStore } from '../../stores/appStore';
import { Button, Input, Modal, TextArea, showConfirm, showToast } from '../common';

type CenterTab = 'skills' | 'templates';
type LearnedSkillDraft = { name: string; summary: string; steps: string; applicableAgents: string; templateId: string; verified: boolean };
type TemplateDraft = {
  templateId: string;
  expectedVersion?: number;
  name: string;
  industry: string;
  targetCustomer: string;
  platforms: string;
  keywords: string;
  leadRules: string;
  replyStyle: string;
};

const EMPTY_SKILL_DRAFT: LearnedSkillDraft = {
  name: '',
  summary: '',
  steps: '',
  applicableAgents: 'LumiAgent, Codex Desktop, Codex CLI',
  templateId: '',
  verified: false,
};
const EMPTY_TEMPLATE_DRAFT: TemplateDraft = {
  templateId: '',
  name: '',
  industry: '',
  targetCustomer: '',
  platforms: 'manual',
  keywords: '',
  leadRules: '',
  replyStyle: '自然、不强推、先确认需求',
};

function splitLines(value: string): string[] {
  return value
    .split(/[\r\n,，]+/)
    .map((item) => item.trim())
    .filter((item, index, values) => Boolean(item) && values.indexOf(item) === index);
}

function formatTime(value?: string | null): string {
  if (!value) return '尚未调用';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

function skillSourceLabel(skill: SkillSummary): string {
  if (skill.source === 'learned') return 'Agent 沉淀';
  return skill.sourceLabel || (skill.source === 'uploaded' ? '导入安装' : '系统内置');
}

function templateUploadLabel(template: AcquisitionTemplateSummary): string {
  if (template.uploadStatus === 'uploaded') return '云端已同步';
  if (template.uploadStatus === 'upload_failed') return '同步失败';
  return '等待云同步';
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('读取文件失败'));
    reader.readAsDataURL(file);
  });
}

function downloadBase64(filename: string, mimeType: string, data: string): void {
  const binary = window.atob(data);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const url = URL.createObjectURL(new Blob([bytes], { type: mimeType || 'application/zip' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const Metric: React.FC<{ label: string; value: React.ReactNode; detail: string; icon: React.ReactNode }> = ({ label, value, detail, icon }) => (
  <div className="relative overflow-hidden rounded-[10px] border border-border bg-surface-alt p-4 shadow-elevation-low">
    <div className="absolute right-[-18px] top-[-24px] h-20 w-20 rounded-full bg-accent/10 blur-2xl" />
    <div className="flex items-start justify-between gap-3">
      <div>
        <div className="text-[11px] font-black uppercase tracking-[0.16em] text-text-subtle">{label}</div>
        <div className="mt-2 text-3xl font-black tabular-nums text-text">{value}</div>
        <div className="mt-1 text-[11px] font-semibold text-text-muted">{detail}</div>
      </div>
      <div className="rounded-[8px] border border-accent/20 bg-accent/10 p-2 text-accent">{icon}</div>
    </div>
  </div>
);

const EmptyState: React.FC<{ title: string; detail: string }> = ({ title, detail }) => (
  <div className="flex min-h-52 flex-col items-center justify-center rounded-[10px] border border-dashed border-border-strong bg-surface/35 px-6 text-center">
    <Sparkles className="mb-3 h-7 w-7 text-accent/75" />
    <div className="text-sm font-black text-text">{title}</div>
    <div className="mt-1 max-w-md text-xs leading-5 text-text-muted">{detail}</div>
  </div>
);

export const SkillCenterPage: React.FC = () => {
  const openFeature = useAppStore((state) => state.openFeature);
  const importInputRef = React.useRef<HTMLInputElement>(null);
  const [tab, setTab] = React.useState<CenterTab>('skills');
  const [skillData, setSkillData] = React.useState<SkillListResponse>({ skills: [] });
  const [templateData, setTemplateData] = React.useState<AcquisitionTemplateStatus>({ templates: [] });
  const [selectedSkillId, setSelectedSkillId] = React.useState('');
  const [search, setSearch] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState('');
  const [loadError, setLoadError] = React.useState('');
  const [readme, setReadme] = React.useState<{ title: string; content: string } | null>(null);
  const [learnOpen, setLearnOpen] = React.useState(false);
  const [learnDraft, setLearnDraft] = React.useState<LearnedSkillDraft>(EMPTY_SKILL_DRAFT);
  const [bindingTemplateId, setBindingTemplateId] = React.useState('');
  const [templateOpen, setTemplateOpen] = React.useState(false);
  const [templateDraft, setTemplateDraft] = React.useState<TemplateDraft>(EMPTY_TEMPLATE_DRAFT);

  const loadAll = React.useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setLoadError('');
    const [skillsResult, templatesResult] = await Promise.allSettled([skillsApi.list(), acquisitionApi.templates()]);
    if (skillsResult.status === 'fulfilled') setSkillData(skillsResult.value);
    if (templatesResult.status === 'fulfilled') setTemplateData(templatesResult.value);
    const errors = [skillsResult, templatesResult]
      .filter((result) => result.status === 'rejected')
      .map((result) => parseErrorText((result as PromiseRejectedResult).reason))
      .filter(Boolean);
    if (errors.length) setLoadError(errors.join('；'));
    setLoading(false);
  }, []);

  React.useEffect(() => { void loadAll(); }, [loadAll]);
  React.useEffect(() => {
    const skills = skillData.skills || [];
    if (!selectedSkillId || !skills.some((skill) => skill.id === selectedSkillId)) setSelectedSkillId(skills[0]?.id || '');
  }, [selectedSkillId, skillData.skills]);

  const skills = skillData.skills || [];
  const templates = templateData.templates || [];
  const normalizedSearch = search.trim().toLowerCase();
  const filteredSkills = skills.filter((skill) => !normalizedSearch || [skill.name, skill.id, skill.description, skill.category, ...(skill.applicableAgents || [])]
    .some((value) => String(value || '').toLowerCase().includes(normalizedSearch)));
  const filteredTemplates = templates.filter((template) => !normalizedSearch || [template.name, template.templateId, template.industry, template.targetCustomer, ...(template.platforms || [])]
    .some((value) => String(value || '').toLowerCase().includes(normalizedSearch)));
  const selectedSkill = skills.find((skill) => skill.id === selectedSkillId) || filteredSkills[0];
  const enabledSkills = skills.filter((skill) => skill.enabled !== false).length;
  const totalInvocations = skills.reduce((total, skill) => total + Number(skill.invocationCount || 0), 0);

  const refresh = async () => {
    setBusy('refresh');
    try {
      await loadAll(true);
      showToast('Skill 与共享模板状态已刷新', 'success');
    } finally { setBusy(''); }
  };

  const importSkill = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.zip')) return showToast('请选择 .zip 格式的 Skill 包', 'error');
    if (file.size > 32 * 1024 * 1024) return showToast('Skill 压缩包不能超过 32MB', 'error');
    setBusy('import');
    try {
      const result = await skillsApi.installZip(file.name, await readFileAsDataUrl(file));
      await loadAll(true);
      setSelectedSkillId(result.skill.id);
      showToast(`已安全导入 ${result.skill.name}`, 'success');
    } catch (error) { showToast(parseErrorText(error) || 'Skill 导入失败，原版本已保留', 'error'); }
    finally { setBusy(''); }
  };

  const toggleSkill = async (skill: SkillSummary) => {
    setBusy(`skill:${skill.id}`);
    try {
      await skillsApi.setEnabled(skill.id, skill.enabled === false);
      await loadAll(true);
      showToast(skill.enabled === false ? 'Skill 已启用' : 'Skill 已停用', 'success');
    } catch (error) { showToast(parseErrorText(error) || 'Skill 状态更新失败', 'error'); }
    finally { setBusy(''); }
  };

  const removeSkill = async (skill: SkillSummary) => {
    const accepted = await showConfirm({ title: '删除这个 Skill？', message: `将删除“${skill.name}”的本地文件。系统内置 Skill 不可删除；历史任务记录会保留。`, confirmText: '删除 Skill', tone: 'danger' });
    if (!accepted) return;
    setBusy(`skill:${skill.id}`);
    try {
      await skillsApi.uninstall(skill.id);
      await loadAll(true);
      showToast('Skill 已删除', 'success');
    } catch (error) { showToast(parseErrorText(error) || 'Skill 删除失败', 'error'); }
    finally { setBusy(''); }
  };

  const exportSkill = async (skill: SkillSummary) => {
    setBusy(`skill:${skill.id}`);
    try {
      const result = await skillsApi.exportZip(skill.id);
      downloadBase64(result.filename, result.mimeType, result.data);
      showToast('Skill 导出已开始', 'success');
    } catch (error) { showToast(parseErrorText(error) || 'Skill 导出失败', 'error'); }
    finally { setBusy(''); }
  };

  const openReadme = async (skill: SkillSummary) => {
    setBusy(`skill:${skill.id}`);
    try {
      const result = await skillsApi.readme(skill.id);
      setReadme({ title: `${skill.name} · 使用说明`, content: result.content });
    } catch (error) { showToast(parseErrorText(error) || '这个 Skill 暂无说明', 'error'); }
    finally { setBusy(''); }
  };

  const createLearnedSkill = async () => {
    const steps = splitLines(learnDraft.steps);
    if (!learnDraft.name.trim() || !learnDraft.summary.trim() || !steps.length) return showToast('请填写名称、用途和至少一个复用步骤', 'error');
    if (!learnDraft.verified) return showToast('请先确认这是已成功验证的确定性只读流程', 'error');
    const linkedTemplate = templates.find((template) => template.templateId === learnDraft.templateId && template.enabled !== false);
    const accepted = await showConfirm({ title: '确认沉淀为 Skill', message: '麓鸣只保存说明与确定性复用步骤，不保存授权码、Token、聊天原文或任意执行脚本。后续遇到副作用动作仍会再次请求确认。', confirmText: '确认沉淀' });
    if (!accepted) return;
    setBusy('learn');
    try {
      const result = await skillsApi.learn({
        name: learnDraft.name.trim(), summary: learnDraft.summary.trim(), steps,
        applicableAgents: splitLines(learnDraft.applicableAgents), confirmed: true,
        verifiedSuccess: true, deterministic: true, sideEffects: false,
        ...(linkedTemplate ? { templateId: linkedTemplate.templateId, templateVersion: linkedTemplate.version || 1 } : {}),
      });
      setLearnOpen(false);
      setLearnDraft(EMPTY_SKILL_DRAFT);
      await loadAll(true);
      setSelectedSkillId(result.skill.id);
      showToast('成功任务已沉淀为可复用 Skill', 'success');
    } catch (error) { showToast(parseErrorText(error) || 'Skill 沉淀失败', 'error'); }
    finally { setBusy(''); }
  };

  const bindSharedTemplate = async () => {
    const skill = selectedSkill;
    const template = templates.find((item) => item.templateId === bindingTemplateId && item.enabled !== false);
    if (!skill || !template) return showToast('请选择一个已启用的共享模板', 'error');
    setBusy(`binding:${skill.id}`);
    try {
      await skillsApi.setTemplateBinding({ id: skill.id, templateId: template.templateId, templateVersion: template.version || 1, linked: true });
      setBindingTemplateId('');
      await loadAll(true);
      showToast('共享模板已按当前版本绑定；执行 Skill 时会严格校验', 'success');
    } catch (error) { showToast(parseErrorText(error) || '共享模板绑定失败，请刷新后重试', 'error'); }
    finally { setBusy(''); }
  };

  const unbindSharedTemplate = async (templateId: string, version: number) => {
    const skill = selectedSkill;
    if (!skill) return;
    setBusy(`binding:${skill.id}`);
    try {
      await skillsApi.setTemplateBinding({ id: skill.id, templateId, templateVersion: version, linked: false });
      await loadAll(true);
      showToast('已解除共享模板绑定', 'success');
    } catch (error) { showToast(parseErrorText(error) || '解除模板绑定失败', 'error'); }
    finally { setBusy(''); }
  };

  const openTemplateEditor = (template?: AcquisitionTemplateSummary) => {
    setTemplateDraft(template ? {
      templateId: template.templateId, expectedVersion: template.version, name: template.name || '', industry: template.industry || '',
      targetCustomer: template.targetCustomer || '', platforms: (template.platforms || []).join(', '),
      keywords: (template.keywords || []).join(', '), leadRules: (template.leadRules || []).join('\n'),
      replyStyle: template.replyStyle || '自然、不强推、先确认需求',
    } : EMPTY_TEMPLATE_DRAFT);
    setTemplateOpen(true);
  };

  const saveTemplate = async () => {
    if (!templateDraft.name.trim() || !templateDraft.industry.trim()) return showToast('请填写模板名称和行业', 'error');
    setBusy('template-save');
    try {
      await acquisitionApi.saveTemplate({
        templateId: templateDraft.templateId || undefined, expectedVersion: templateDraft.expectedVersion,
        name: templateDraft.name.trim(), industry: templateDraft.industry.trim(), targetCustomer: templateDraft.targetCustomer.trim(),
        platforms: splitLines(templateDraft.platforms), keywords: splitLines(templateDraft.keywords),
        leadRules: splitLines(templateDraft.leadRules), replyStyle: templateDraft.replyStyle.trim(),
      });
      setTemplateOpen(false);
      setTemplateDraft(EMPTY_TEMPLATE_DRAFT);
      await loadAll(true);
      showToast('共享模板已保存', 'success');
    } catch (error) { showToast(parseErrorText(error) || '共享模板保存失败，请刷新后重试', 'error'); }
    finally { setBusy(''); }
  };

  const toggleTemplate = async (template: AcquisitionTemplateSummary) => {
    setBusy(`template:${template.templateId}`);
    try {
      await acquisitionApi.setTemplateEnabled(template.templateId, template.enabled === false, template.version);
      await loadAll(true);
      showToast(template.enabled === false ? '共享模板已启用' : '共享模板已停用', 'success');
    } catch (error) { showToast(parseErrorText(error) || '模板状态更新失败，请刷新后重试', 'error'); }
    finally { setBusy(''); }
  };

  const uploadTemplate = async (template: AcquisitionTemplateSummary) => {
    setBusy(`template:${template.templateId}`);
    try {
      await acquisitionApi.uploadTemplate(template.templateId);
      await loadAll(true);
      showToast('模板云同步已处理', 'success');
    } catch (error) { showToast(parseErrorText(error) || '模板云同步失败', 'error'); }
    finally { setBusy(''); }
  };

  const deleteTemplate = async (template: AcquisitionTemplateSummary) => {
    const accepted = await showConfirm({ title: '删除共享模板？', message: `将删除“${template.name}”的本地共享版本；正在运行的矩阵任务不会被中断。`, confirmText: '删除模板', tone: 'danger' });
    if (!accepted) return;
    setBusy(`template:${template.templateId}`);
    try {
      await acquisitionApi.deleteTemplate(template.templateId, template.version);
      await loadAll(true);
      showToast('共享模板已删除', 'success');
    } catch (error) { showToast(parseErrorText(error) || '模板删除失败，请刷新后重试', 'error'); }
    finally { setBusy(''); }
  };

  const setCloudConsent = async (enabled: boolean) => {
    const accepted = !enabled || await showConfirm({ title: '允许同步共享模板？', message: '只会上传脱敏后的模板结构，不上传授权码、Token、手机号、邮箱或原始聊天内容。你可以随时关闭。', confirmText: '允许同步' });
    if (!accepted) return;
    setBusy('cloud');
    try {
      await acquisitionApi.setTemplateCloudConsent(enabled, enabled);
      await loadAll(true);
      showToast(enabled ? '云模板同步已开启' : '云模板同步已关闭', 'success');
    } catch (error) { showToast(parseErrorText(error) || '云模板设置失败', 'error'); }
    finally { setBusy(''); }
  };

  const retryTemplates = async () => {
    setBusy('cloud');
    try {
      await acquisitionApi.retryTemplates();
      await loadAll(true);
      showToast('已重试等待中的模板', 'success');
    } catch (error) { showToast(parseErrorText(error) || '模板重试失败', 'error'); }
    finally { setBusy(''); }
  };

  return (
    <div data-shared-skill-center className="absolute inset-0 overflow-y-auto bg-surface">
      <div className="mx-auto min-h-full max-w-[1540px] px-5 py-5 lg:px-8 lg:py-7">
        <header className="relative overflow-hidden rounded-[12px] border border-border-strong bg-app-sidebar px-6 py-6 text-white shadow-elevation-high lg:px-8">
          <div className="pointer-events-none absolute inset-y-0 right-0 w-2/5 bg-accent/10" />
          <div className="relative flex flex-col justify-between gap-5 xl:flex-row xl:items-end">
            <div className="max-w-3xl">
              <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.22em] text-accent"><Zap className="h-4 w-4" /> Matrix Memory Layer</div>
              <h1 className="mt-3 text-3xl font-black tracking-tight lg:text-4xl">Skill 与共享模板中心</h1>
              <p className="mt-3 max-w-2xl text-sm font-semibold leading-6 text-white/65">第一次完成并验证，沉淀成可复用方法；第二次让 Agent 直接调用。手机矩阵、获客、飞书流转和云模板共用同一份矩阵授权。</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="quiet" onClick={() => void refresh()} disabled={busy === 'refresh'} className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"><span className="flex items-center gap-2"><RefreshCw className={`h-4 w-4 ${busy === 'refresh' ? 'animate-spin' : ''}`} />刷新</span></Button>
              <Button variant="primary" onClick={() => setLearnOpen(true)}><span className="flex items-center gap-2"><Sparkles className="h-4 w-4" />从成功任务沉淀</span></Button>
            </div>
          </div>
        </header>

        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <Metric label="可调用 Skill" value={`${enabledSkills}/${skills.length}`} detail="启用后供桌面与 LumiAgent 选择" icon={<BookOpen className="h-5 w-5" />} />
          <Metric label="累计复用" value={totalInvocations} detail="每次调用都会留下本地可审计记录" icon={<History className="h-5 w-5" />} />
          <Metric label="共享模板" value={templates.length} detail="与手机矩阵、获客、飞书共用" icon={<Cloud className="h-5 w-5" />} />
        </div>

        <section className="mt-4 rounded-[12px] border border-border bg-surface-alt shadow-elevation-low">
          <div className="flex flex-col gap-3 border-b border-border p-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex rounded-[9px] border border-border bg-surface p-1">
              {([['skills', 'Skill 中心', Sparkles], ['templates', '共享模板', Cloud]] as const).map(([key, label, TabIcon]) => (
                <button key={key} type="button" onClick={() => setTab(key)} className={`flex min-h-9 items-center gap-2 rounded-[7px] px-4 text-xs font-black transition ${tab === key ? 'bg-accent text-accent-ink shadow-elevation-low' : 'text-text-muted hover:bg-hover hover:text-text'}`}><TabIcon className="h-4 w-4" />{label}</button>
              ))}
            </div>
            <div className="flex flex-1 items-center gap-2 lg:max-w-xl">
              <div className="relative flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-subtle" /><Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={tab === 'skills' ? '搜索名称、ID、用途或适用 Agent' : '搜索模板、行业或平台'} className="pl-9" /></div>
              {tab === 'skills' ? <><input ref={importInputRef} type="file" accept=".zip,application/zip" className="hidden" onChange={(event) => void importSkill(event)} /><Button variant="quiet" onClick={() => importInputRef.current?.click()} disabled={busy === 'import'}><span className="flex items-center gap-2"><Upload className="h-4 w-4" />导入 Skill</span></Button></> : <Button variant="primary" onClick={() => openTemplateEditor()}><span className="flex items-center gap-2"><Plus className="h-4 w-4" />新建模板</span></Button>}
            </div>
          </div>

          {loadError ? <div className="mx-4 mt-4 rounded-[8px] border border-status-danger bg-status-danger-soft px-4 py-3 text-xs font-bold text-status-danger-ink">{loadError}</div> : null}
          {loading ? <div className="flex min-h-[380px] items-center justify-center text-sm font-bold text-text-muted">正在读取本机 Skill 与共享模板…</div> : tab === 'skills' ? (
            <div className="grid min-h-[520px] lg:grid-cols-[minmax(330px,0.78fr)_minmax(480px,1.22fr)]">
              <div className="border-b border-border p-3 lg:border-b-0 lg:border-r">
                <div className="mb-2 flex items-center justify-between px-1 text-[11px] font-black uppercase tracking-[0.12em] text-text-subtle"><span>{filteredSkills.length} 个结果</span><span>本地优先</span></div>
                <div className="max-h-[640px] space-y-2 overflow-y-auto pr-1">
                  {filteredSkills.map((skill) => <button key={skill.id} type="button" onClick={() => setSelectedSkillId(skill.id)} className={`w-full rounded-[9px] border p-4 text-left transition ${selectedSkill?.id === skill.id ? 'border-accent bg-accent/10 ring-1 ring-accent/30' : 'border-border bg-surface hover:border-border-strong hover:bg-hover'}`}>
                    <div className="flex items-start gap-3"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[8px] border border-border-strong bg-surface-alt text-xs font-black text-accent">{(skill.icon || 'SK').slice(0, 2).toUpperCase()}</div><div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2"><div className="truncate text-sm font-black text-text">{skill.name}</div><span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-black ${skill.enabled === false ? 'bg-disabled text-disabled' : 'bg-status-success-soft text-status-success-ink'}`}>{skill.enabled === false ? '已停用' : '可调用'}</span></div>
                      <div className="mt-1 line-clamp-2 text-xs leading-5 text-text-muted">{skill.description || '暂无用途说明'}</div>
                      <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] font-bold text-text-subtle"><span>{skillSourceLabel(skill)}</span><span>·</span><span>v{skill.version || '0.0.0'}</span><span>·</span><span>{skill.invocationCount || 0} 次</span></div>
                    </div></div>
                  </button>)}
                  {!filteredSkills.length ? <EmptyState title="没有匹配的 Skill" detail="清空搜索，或导入一个安全的 Skill 压缩包。" /> : null}
                </div>
              </div>
              <div className="p-5 lg:p-6">
                {selectedSkill ? <div>
                  <div className="flex flex-col justify-between gap-4 border-b border-border pb-5 md:flex-row md:items-start"><div><div className="flex flex-wrap items-center gap-2"><span className="rounded-full border border-accent/20 bg-accent/10 px-2.5 py-1 text-[10px] font-black text-accent">{skillSourceLabel(selectedSkill)}</span><span className="text-[11px] font-bold text-text-subtle">{selectedSkill.id}</span></div><h2 className="mt-3 text-2xl font-black text-text">{selectedSkill.name}</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">{selectedSkill.description || '这个 Skill 暂未提供用途说明。'}</p></div><div className="flex flex-wrap gap-2"><Button variant="quiet" onClick={() => void toggleSkill(selectedSkill)} disabled={busy === `skill:${selectedSkill.id}`}>{selectedSkill.enabled === false ? '启用' : '停用'}</Button><Button variant="quiet" onClick={() => void exportSkill(selectedSkill)} disabled={busy === `skill:${selectedSkill.id}`}><span className="flex items-center gap-2"><Download className="h-4 w-4" />导出</span></Button></div></div>
                  <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <div className="rounded-[9px] border border-border bg-surface p-4"><div className="text-[10px] font-black uppercase tracking-wider text-text-subtle">调用次数</div><div className="mt-2 text-xl font-black text-text">{selectedSkill.invocationCount || 0}</div></div>
                    <div className="rounded-[9px] border border-border bg-surface p-4"><div className="text-[10px] font-black uppercase tracking-wider text-text-subtle">成功调用</div><div className="mt-2 text-xl font-black text-text">{selectedSkill.successfulInvocations || 0}</div></div>
                    <div className="rounded-[9px] border border-border bg-surface p-4"><div className="text-[10px] font-black uppercase tracking-wider text-text-subtle">最近使用</div><div className="mt-2 text-xs font-black leading-5 text-text">{formatTime(selectedSkill.lastUsedAt)}</div></div>
                    <div className="rounded-[9px] border border-border bg-surface p-4"><div className="text-[10px] font-black uppercase tracking-wider text-text-subtle">最近耗时</div><div className="mt-2 text-xl font-black text-text">{selectedSkill.lastDurationMs ? `${selectedSkill.lastDurationMs}ms` : '—'}</div></div>
                  </div>
                  <div className="mt-5 grid gap-4 xl:grid-cols-2">
                    <div className="rounded-[10px] border border-border bg-surface p-5"><div className="flex items-center gap-2 text-sm font-black text-text"><Smartphone className="h-4 w-4 text-accent" />适用 Agent</div><div className="mt-3 flex flex-wrap gap-2">{(selectedSkill.applicableAgents?.length ? selectedSkill.applicableAgents : ['按 Skill 说明选择']).map((agent) => <span key={agent} className="rounded-full border border-border-strong bg-surface-alt px-3 py-1.5 text-[11px] font-bold text-text-muted">{agent}</span>)}</div><div className="mt-4 border-t border-border pt-4 text-xs leading-5 text-text-muted">运行时：<strong className="text-text">{selectedSkill.runtime || 'instruction'}</strong> · 最近 Agent：<strong className="text-text">{selectedSkill.lastAgent || '尚无记录'}</strong></div></div>
                    <div className="rounded-[10px] border border-border bg-surface p-5"><div className="flex items-center gap-2 text-sm font-black text-text"><ShieldCheck className="h-4 w-4 text-accent" />安全复用边界</div><ul className="mt-3 space-y-2 text-xs leading-5 text-text-muted"><li>• 沉淀只保存脱敏步骤，不保存授权码、Token 或原聊天。</li><li>• 删除、发布、付款等副作用动作每次仍需重新确认。</li><li>• 手机 Linux 仅执行允许列表内的确定性工作区任务。</li></ul></div>
                  </div>
                  <div className="mt-4 rounded-[10px] border border-border bg-surface p-5">
                    <div className="flex items-center gap-2 text-sm font-black text-text"><Cloud className="h-4 w-4 text-accent" />绑定共享模板</div>
                    <p className="mt-2 text-xs leading-5 text-text-muted">手机矩阵、获客和飞书共用这里的模板；绑定会固定当前版本，模板更新或停用后会先阻止执行并提示重新绑定。</p>
                    <div className="mt-3 flex flex-wrap gap-2">{(selectedSkill.linkedTemplates || []).map((binding) => <span key={`${binding.templateId}@${binding.version}`} className="inline-flex items-center gap-2 rounded-full border border-border-strong bg-surface-alt px-3 py-1.5 text-[11px] font-bold text-text-muted"><span>{binding.name || binding.templateId} · v{binding.version}</span><button type="button" className="text-status-danger-ink hover:underline" onClick={() => void unbindSharedTemplate(binding.templateId, binding.version)}>解除</button></span>)}{!selectedSkill.linkedTemplates?.length ? <span className="text-xs text-text-subtle">尚未绑定，可直接复用纯 Skill 步骤。</span> : null}</div>
                    <div className="mt-4 flex flex-col gap-2 sm:flex-row"><select aria-label="选择共享模板" value={bindingTemplateId} onChange={(event) => setBindingTemplateId(event.target.value)} className="min-h-10 flex-1 rounded-[8px] border border-border-strong bg-surface-alt px-3 text-xs font-bold text-text outline-none focus:border-accent"><option value="">选择已启用的共享模板</option>{templates.filter((template) => template.enabled !== false).map((template) => <option key={template.templateId} value={template.templateId}>{template.name} · v{template.version || 1}</option>)}</select><Button variant="quiet" disabled={busy === `binding:${selectedSkill.id}` || !bindingTemplateId} onClick={() => void bindSharedTemplate()}>绑定 / 更新版本</Button></div>
                  </div>
                  <div className="mt-5 flex flex-wrap gap-2">{selectedSkill.hasReadme ? <Button variant="quiet" onClick={() => void openReadme(selectedSkill)}><span className="flex items-center gap-2"><BookOpen className="h-4 w-4" />查看说明</span></Button> : null}{selectedSkill.writable ? <Button variant="danger" onClick={() => void removeSkill(selectedSkill)}><span className="flex items-center gap-2"><Trash2 className="h-4 w-4" />删除</span></Button> : null}</div>
                </div> : <EmptyState title="还没有可用 Skill" detail="先完成一次可验证任务，再从右上角沉淀；也可以导入符合规范的 Skill 包。" />}
              </div>
            </div>
          ) : <div className="p-4 lg:p-5">
            <div className="mb-4 grid gap-3 xl:grid-cols-[1.35fr_0.65fr]">
              <div className="rounded-[10px] border border-border bg-surface p-5"><div className="flex flex-col justify-between gap-4 md:flex-row md:items-center"><div><div className="flex items-center gap-2 text-sm font-black text-text"><Cloud className="h-4 w-4 text-accent" />云模板同步</div><p className="mt-2 text-xs leading-5 text-text-muted">模板与手机矩阵共用授权。只有明确同意后才上传脱敏结构；飞书流转只是运行时连接条件，不再额外收费。</p></div><div className="flex flex-wrap gap-2"><Button variant="quiet" onClick={() => void retryTemplates()} disabled={busy === 'cloud'}><span className="flex items-center gap-2"><RefreshCw className="h-4 w-4" />重试待同步</span></Button><Button variant={templateData.cloud?.consentGranted ? 'danger' : 'primary'} onClick={() => void setCloudConsent(!templateData.cloud?.consentGranted)} disabled={busy === 'cloud'}>{templateData.cloud?.consentGranted ? '关闭云同步' : '允许云同步'}</Button></div></div></div>
              <div className="rounded-[10px] border border-accent/20 bg-accent/10 p-5"><div className="text-[10px] font-black uppercase tracking-[0.16em] text-accent">同一执行面</div><div className="mt-2 text-sm font-black text-text">手机矩阵 → 获客 → 模板 → 飞书</div><button type="button" onClick={() => openFeature('workbench')} className="mt-4 flex items-center gap-2 text-xs font-black text-accent hover:underline">进入矩阵工作台 <ArrowRight className="h-4 w-4" /></button></div>
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{filteredTemplates.map((template) => <article key={template.templateId} className={`rounded-[10px] border bg-surface p-5 transition ${template.enabled === false ? 'border-border opacity-65' : 'border-border-strong hover:border-accent/35'}`}>
              <div className="flex items-start justify-between gap-3"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className={`rounded-full px-2 py-1 text-[10px] font-black ${template.uploadStatus === 'uploaded' ? 'bg-status-success-soft text-status-success-ink' : template.uploadStatus === 'upload_failed' ? 'bg-status-danger-soft text-status-danger-ink' : 'bg-status-warning-soft text-status-warning-ink'}`}>{templateUploadLabel(template)}</span><span className="text-[10px] font-bold text-text-subtle">v{template.version || 1}</span></div><h3 className="mt-3 truncate text-lg font-black text-text">{template.name}</h3><p className="mt-1 text-xs font-bold text-text-muted">{template.industry || '通用'} · {(template.platforms || ['manual']).join(' / ')}</p></div><button type="button" onClick={() => void toggleTemplate(template)} disabled={busy === `template:${template.templateId}`} className={`rounded-full px-3 py-1.5 text-[10px] font-black ${template.enabled === false ? 'bg-disabled text-disabled' : 'bg-accent/10 text-accent'}`}>{template.enabled === false ? '已停用' : '已启用'}</button></div>
              <div className="mt-4 min-h-16 rounded-[8px] border border-border bg-surface-alt px-3 py-3 text-xs leading-5 text-text-muted">{template.targetCustomer || '尚未填写目标客户；编辑模板后可供矩阵任务直接复用。'}</div>{template.uploadError ? <div className="mt-3 text-[11px] font-bold text-status-danger-ink">{template.uploadError}</div> : null}
              <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4"><Button variant="quiet" className="min-h-9 px-3 py-1.5 text-xs" onClick={() => openTemplateEditor(template)}><span className="flex items-center gap-1.5"><Pencil className="h-3.5 w-3.5" />编辑</span></Button><Button variant="quiet" className="min-h-9 px-3 py-1.5 text-xs" onClick={() => void uploadTemplate(template)} disabled={busy === `template:${template.templateId}`}><span className="flex items-center gap-1.5"><Upload className="h-3.5 w-3.5" />同步</span></Button><Button variant="danger" className="min-h-9 px-3 py-1.5 text-xs" onClick={() => void deleteTemplate(template)} disabled={busy === `template:${template.templateId}`}><Trash2 className="h-3.5 w-3.5" /></Button></div>
            </article>)}</div>
            {!filteredTemplates.length ? <EmptyState title="还没有共享模板" detail="从获客任务保存一份打法，或点击“新建模板”；同一模板随后可被手机矩阵和飞书流转调用。" /> : null}
          </div>}
        </section>
      </div>

      <Modal isOpen={learnOpen} onClose={() => setLearnOpen(false)} title="从成功任务沉淀 Skill" panelClassName="max-w-2xl"><div className="space-y-4">
        <div className="rounded-[8px] border border-accent/20 bg-accent/10 px-4 py-3 text-xs leading-5 text-text-muted">只沉淀已成功验证、结果确定且无副作用的步骤。发布、付款、删除、私信等动作不能直接进入快速复用。</div>
        <label className="block text-xs font-black text-text">名称<Input className="mt-2" value={learnDraft.name} onChange={(event) => setLearnDraft({ ...learnDraft, name: event.target.value })} placeholder="例如：批量整理客户需求表" /></label>
        <label className="block text-xs font-black text-text">用途说明<TextArea className="mt-2 min-h-20" value={learnDraft.summary} onChange={(event) => setLearnDraft({ ...learnDraft, summary: event.target.value })} placeholder="说明什么时候调用、输入和输出是什么" /></label>
        <label className="block text-xs font-black text-text">复用步骤（每行一步）<TextArea className="mt-2 min-h-32 font-mono" value={learnDraft.steps} onChange={(event) => setLearnDraft({ ...learnDraft, steps: event.target.value })} placeholder={'读取工作区输入\n校验格式\n输出结果并保留原文件'} /></label>
        <label className="block text-xs font-black text-text">适用 Agent<Input className="mt-2" value={learnDraft.applicableAgents} onChange={(event) => setLearnDraft({ ...learnDraft, applicableAgents: event.target.value })} /></label>
        <label className="block text-xs font-black text-text">关联共享模板（可选）<select value={learnDraft.templateId} onChange={(event) => setLearnDraft({ ...learnDraft, templateId: event.target.value })} className="mt-2 min-h-10 w-full rounded-[8px] border border-border-strong bg-surface-alt px-3 text-xs font-bold text-text outline-none focus:border-accent"><option value="">不关联模板</option>{templates.filter((template) => template.enabled !== false).map((template) => <option key={template.templateId} value={template.templateId}>{template.name} · v{template.version || 1}</option>)}</select><span className="mt-1 block text-[11px] font-normal leading-5 text-text-muted">选择后会固定 templateId 与 templateVersion，执行时严格校验，不会静默换成其他版本。</span></label>
        <label className="flex cursor-pointer items-start gap-3 rounded-[8px] border border-border bg-surface-alt p-3 text-xs leading-5 text-text-muted"><input type="checkbox" checked={learnDraft.verified} onChange={(event) => setLearnDraft({ ...learnDraft, verified: event.target.checked })} className="mt-1 accent-[var(--color-accent)]" /><span>我确认这个流程已经成功运行并人工核对，步骤是确定性的、只读或只写新输出，不包含对外发布、付款、删除、提权或任意脚本。</span></label>
        <div className="flex justify-end gap-2"><Button variant="quiet" onClick={() => setLearnOpen(false)}>取消</Button><Button variant="primary" disabled={busy === 'learn' || !learnDraft.verified} onClick={() => void createLearnedSkill()}>{busy === 'learn' ? '正在沉淀…' : '确认沉淀'}</Button></div>
      </div></Modal>

      <Modal isOpen={templateOpen} onClose={() => setTemplateOpen(false)} title={templateDraft.templateId ? '编辑共享模板' : '新建共享模板'} panelClassName="max-w-3xl">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="block text-xs font-black text-text">模板名称<Input className="mt-2" value={templateDraft.name} onChange={(event) => setTemplateDraft({ ...templateDraft, name: event.target.value })} placeholder="例如：本地美业评论区获客" /></label>
          <label className="block text-xs font-black text-text">行业<Input className="mt-2" value={templateDraft.industry} onChange={(event) => setTemplateDraft({ ...templateDraft, industry: event.target.value })} placeholder="美业 / 家政 / 装修" /></label>
          <label className="block text-xs font-black text-text md:col-span-2">目标客户<Input className="mt-2" value={templateDraft.targetCustomer} onChange={(event) => setTemplateDraft({ ...templateDraft, targetCustomer: event.target.value })} placeholder="描述最适合这套打法的客户" /></label>
          <label className="block text-xs font-black text-text">平台（逗号分隔）<Input className="mt-2" value={templateDraft.platforms} onChange={(event) => setTemplateDraft({ ...templateDraft, platforms: event.target.value })} placeholder="douyin, xiaohongshu" /></label>
          <label className="block text-xs font-black text-text">关键词（逗号分隔）<Input className="mt-2" value={templateDraft.keywords} onChange={(event) => setTemplateDraft({ ...templateDraft, keywords: event.target.value })} /></label>
          <label className="block text-xs font-black text-text">线索判断规则（每行一条）<TextArea className="mt-2 min-h-28" value={templateDraft.leadRules} onChange={(event) => setTemplateDraft({ ...templateDraft, leadRules: event.target.value })} /></label>
          <label className="block text-xs font-black text-text">回复风格<TextArea className="mt-2 min-h-28" value={templateDraft.replyStyle} onChange={(event) => setTemplateDraft({ ...templateDraft, replyStyle: event.target.value })} /></label>
        </div>
        <div className="mt-4 rounded-[8px] border border-border bg-surface-alt px-4 py-3 text-[11px] leading-5 text-text-muted">保存会使用 <code>expectedVersion</code> 防止多人或多个 Agent 并发覆盖；若模板已更新，请先刷新再编辑。</div>
        <div className="mt-5 flex justify-end gap-2"><Button variant="quiet" onClick={() => setTemplateOpen(false)}>取消</Button><Button variant="primary" disabled={busy === 'template-save'} onClick={() => void saveTemplate()}>{busy === 'template-save' ? '正在保存…' : '保存模板'}</Button></div>
      </Modal>

      <Modal isOpen={Boolean(readme)} onClose={() => setReadme(null)} title={readme?.title} panelClassName="max-w-3xl"><pre className="max-h-[58vh] whitespace-pre-wrap break-words rounded-[8px] border border-border bg-app-sidebar p-4 font-mono text-xs leading-6 text-white/80">{readme?.content}</pre></Modal>
    </div>
  );
};
