import React from 'react';

import type { MatrixCampaign, MatrixExecutionMode, MatrixExecutionProfile } from '../../types/matrix';
import { Button, showToast } from '../common';

const PHONE_AGENT_APK_URL = 'https://gitee.com/rfdiosuao/lumiapkclaw/releases/download/lumiclaw13241/OpenClaw-AgentPhone.apk';
const PHONE_AGENT_QR_SRC = '/phone-agent-apk-qr.svg';

interface MatrixTaskDrawerProps {
  open: boolean;
  templateId: string;
  mode: MatrixExecutionMode;
  profile: MatrixExecutionProfile;
  confirmed: boolean;
  campaigns: MatrixCampaign[];
  onTemplateIdChange: (value: string) => void;
  onModeChange: (value: MatrixExecutionMode) => void;
  onProfileChange: (value: MatrixExecutionProfile) => void;
  onConfirmedChange: (value: boolean) => void;
  onClose: () => void;
}

export const MatrixTaskDrawer: React.FC<MatrixTaskDrawerProps> = ({
  open,
  templateId,
  mode,
  profile,
  confirmed,
  campaigns,
  onTemplateIdChange,
  onModeChange,
  onProfileChange,
  onConfirmedChange,
  onClose,
}) => {
  if (!open) return null;
  const copyPhoneAgentUrl = async () => {
    try {
      await navigator.clipboard.writeText(PHONE_AGENT_APK_URL);
      showToast('手机端 App 下载链接已复制', 'success');
    } catch {
      showToast('复制失败，请使用下载按钮直接打开', 'error');
    }
  };
  return (
    <div data-matrix-task-drawer className="absolute inset-0 z-40 flex justify-end bg-black/45" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="h-full w-[340px] overflow-auto border-l border-white/10 bg-[#0A1B26] p-4 shadow-2xl">
        <div className="flex items-center justify-between">
          <div><div className="text-[9px] font-black tracking-[0.18em] text-cyan-200/60">TASK SETTINGS</div><h2 className="mt-1 text-sm font-black text-white">高级参数</h2></div>
          <button type="button" onClick={onClose} aria-label="关闭高级参数" title="关闭" className="h-7 w-7 rounded-[5px] border border-white/10 text-sm text-slate-300">×</button>
        </div>

        <div className="mt-5 space-y-4">
          <label className="block text-[10px] font-bold text-slate-400">
            模板 ID（留空为直接任务）
            <input value={templateId} onChange={(event) => onTemplateIdChange(event.target.value)} className="mt-1.5 w-full rounded-[6px] border border-white/10 bg-[#06131C] px-3 py-2 text-xs text-slate-100 outline-none focus:border-cyan-300/40" />
          </label>
          <label className="block text-[10px] font-bold text-slate-400">
            执行模式
            <select value={mode} onChange={(event) => onModeChange(event.target.value as MatrixExecutionMode)} className="mt-1.5 w-full rounded-[6px] border border-white/10 bg-[#06131C] px-3 py-2 text-xs text-slate-100">
              <option value="observe">只读观察</option><option value="safe">安全控制</option><option value="full">完整控制</option>
            </select>
          </label>
          <label className="block text-[10px] font-bold text-slate-400">
            执行档位
            <select value={profile} onChange={(event) => onProfileChange(event.target.value as MatrixExecutionProfile)} className="mt-1.5 w-full rounded-[6px] border border-white/10 bg-[#06131C] px-3 py-2 text-xs text-slate-100">
              <option value="fast">快速</option><option value="standard">标准</option><option value="deep">深度</option>
            </select>
          </label>
          <label className="flex items-start gap-2 rounded-[6px] border border-amber-300/20 bg-amber-300/8 p-3 text-[10px] leading-4 text-amber-100">
            <input type="checkbox" checked={confirmed} onChange={(event) => onConfirmedChange(event.target.checked)} className="mt-0.5" />
            已确认当前任务作用范围和外部动作风险
          </label>
        </div>

        <div className="mt-6 border-t border-white/[0.08] pt-4">
          <div className="mb-2 flex items-center justify-between"><h3 className="text-[10px] font-black text-slate-200">真实任务历史</h3><span className="text-[9px] text-slate-500">{campaigns.length} 项</span></div>
          <div className="space-y-1.5">
            {campaigns.length ? campaigns.slice().reverse().slice(0, 12).map((campaign) => (
              <div key={campaign.campaignId} className="rounded-[6px] border border-white/[0.07] bg-white/[0.025] p-2 text-[9px]">
                <div className="flex justify-between gap-2"><span className="truncate font-mono text-slate-300">{campaign.campaignId}</span><span className="font-bold text-cyan-100">{campaign.status}</span></div>
                <div className="mt-1 text-slate-500">完成 {campaign.counts.completed}/{campaign.counts.total} · 失败 {campaign.counts.failed}</div>
              </div>
            )) : <div className="py-6 text-center text-[10px] text-slate-600">暂无后端任务历史</div>}
          </div>
        </div>

        <div data-matrix-phone-app-download className="mt-6 border-t border-white/[0.08] pt-4">
          <div className="flex items-start gap-3">
            <img src={PHONE_AGENT_QR_SRC} alt="手机端 App 下载二维码" className="h-16 w-16 shrink-0 rounded-[6px] bg-white p-1" />
            <div className="min-w-0 flex-1">
              <h3 className="text-xs font-black text-white">手机端 App</h3>
              <p className="mt-1 text-[10px] leading-4 text-slate-400">安装后在手机页保存设备地址和令牌，即可加入矩阵。</p>
              <div className="mt-2 flex gap-2">
                <a href={PHONE_AGENT_APK_URL} target="_blank" rel="noreferrer" className="rounded-[6px] border border-cyan-300/25 bg-cyan-300/10 px-2 py-1 text-[10px] font-bold text-cyan-100">下载 APK</a>
                <button type="button" onClick={() => void copyPhoneAgentUrl()} className="rounded-[6px] border border-white/10 px-2 py-1 text-[10px] font-bold text-slate-300">复制链接</button>
              </div>
            </div>
          </div>
        </div>
        <Button variant="primary" onClick={onClose} className="mt-5 w-full !rounded-[6px] !py-2 !text-xs">完成</Button>
      </section>
    </div>
  );
};
