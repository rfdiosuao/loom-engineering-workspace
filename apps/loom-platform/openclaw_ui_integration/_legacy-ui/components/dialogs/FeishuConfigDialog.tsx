import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Command, type Child, type TerminatedPayload } from '@tauri-apps/plugin-shell';
import { Button, FieldLabel, Input, Loading, showToast } from '../common';
import { configApi } from '../../services/api';
import { useLogStore } from '../../stores/logStore';
import { BotInstallConsole } from './BotInstallConsole';
import { CHANNELS } from './botPluginChannels';
import { OPENCLAW_CONFIG_PATH, type BotChannel, type InstallStep, type PluginStatus } from './botPluginTypes';
import {
  buildChannelConfig,
  configHasPlugin,
  getSavedChannelConfig,
  isInstalledPackage,
  makeCommandOptions,
  normalizeCommandOutput,
  resolvePortableBasePath,
} from './botPluginRuntime';

interface PluginCheckCommandResult {
  packageInstalled?: boolean;
  extensionInstalled?: boolean;
  configured?: boolean;
  installed?: boolean;
  savedId?: string;
}

type PluginDetectionState = {
  status: PluginStatus;
  message: string;
  detected: boolean;
};

function summarizePluginDetection(
  channel: BotChannel,
  packageInstalled: boolean,
  extensionInstalled: boolean,
  configured: boolean,
  error?: unknown,
): PluginDetectionState {
  const hasPackage = packageInstalled || extensionInstalled;
  const hasConfig = configured;
  const errorMessage = error instanceof Error ? error.message : String((error as any)?.message || error || '');

  if (!hasPackage && !hasConfig && errorMessage) {
    return {
      status: 'error',
      message: `插件检测失败：${errorMessage}`,
      detected: false,
    };
  }

  if (hasPackage && hasConfig) {
    return {
      status: 'installed',
      message: `${channel.title}插件已安装并写入配置`,
      detected: true,
    };
  }

  if (hasPackage) {
    return {
      status: 'installed',
      message: `${channel.title}插件包已预置，点击安装写入配置`,
      detected: true,
    };
  }

  if (hasConfig) {
    return {
      status: 'installed',
      message: `${channel.title}配置已存在，等待插件包补齐`,
      detected: true,
    };
  }

  return {
    status: 'missing',
    message: `未检测到${channel.title}插件包，请重新打包`,
    detected: false,
  };
}

function parsePluginCheckOutput(output: string): PluginCheckCommandResult {
  const line = output
    .split(/\r?\n/)
    .map((item) => item.trim())
    .reverse()
    .find((item) => item.startsWith('{') && item.endsWith('}'));
  if (!line) {
    throw new Error('检测命令没有返回有效结果');
  }
  return JSON.parse(line) as PluginCheckCommandResult;
}

const BotConfigDialog: React.FC<{ channel: BotChannel; onClose: () => void }> = ({ channel, onClose }) => {
  const [idValue, setIdValue] = useState('');
  const [secretValue, setSecretValue] = useState('');
  const [pluginStatus, setPluginStatus] = useState<PluginStatus>('unknown');
  const [checking, setChecking] = useState(true);
  const [commandRunning, setCommandRunning] = useState(false);
  const [statusMessage, setStatusMessage] = useState(`正在检测${channel.title}插件...`);
  const [commandLog, setCommandLog] = useState<string[]>([]);
  const childRef = useRef<Child | null>(null);
  const outputRef = useRef<HTMLPreElement>(null);
  const stoppingRef = useRef(false);
  const appendMainLog = useLogStore((s) => s.append);

  const installed = pluginStatus === 'installed';
  const commandSummary = useMemo(
    () => channel.installSteps.map((step) => step.displayCommand).join('\n'),
    [channel.installSteps],
  );

  const pushCommandLog = useCallback((text: string, mirrorToServiceLog = true) => {
    const clean = normalizeCommandOutput(text);
    if (!clean) return;
    setCommandLog((items) => [...items, clean]);
    if (mirrorToServiceLog) {
      appendMainLog(`[${channel.title}] ${clean.endsWith('\n') ? clean : `${clean}\n`}`);
    }
  }, [appendMainLog, channel.title]);

  useEffect(() => {
    if (!outputRef.current) return;
    outputRef.current.scrollTop = outputRef.current.scrollHeight;
  }, [commandLog]);

  useEffect(() => {
    return () => {
      childRef.current?.kill().catch(() => undefined);
      childRef.current = null;
    };
  }, []);

  const runLocalPluginCheck = useCallback(async () => {
    const cwd = await resolvePortableBasePath();
    const args = ['scripts/bot-plugin-helper.mjs', 'check', channel.key];
    const options = makeCommandOptions(cwd);

    const run = async (commandName: string) => {
      const output = await Command.create(commandName, args, options).execute();
      const stdout = normalizeCommandOutput(output.stdout);
      const stderr = normalizeCommandOutput(output.stderr);
      if (output.code !== 0) {
        throw new Error(stderr || stdout || `检测命令退出码：${output.code}`);
      }
      return parsePluginCheckOutput(stdout);
    };

    try {
      return await run(`bot-plugin-check-${channel.key}`);
    } catch (error) {
      appendMainLog(`[${channel.title}] 检测命令切换到 node.exe：${error}\n`);
      return await run(`bot-plugin-check-${channel.key}-node-exe`);
    }
  }, [appendMainLog, channel]);

  const checkPlugin = useCallback(async () => {
    setChecking(true);
    setStatusMessage(`正在检测${channel.title}插件...`);

    let packageInstalled = false;
    let extensionInstalled = false;
    let configured = false;
    let detectionError: unknown = null;

    try {
      const status = await runLocalPluginCheck();
      packageInstalled = Boolean(status.packageInstalled);
      extensionInstalled = Boolean(status.extensionInstalled);
      configured = Boolean(status.configured);
      if (status.savedId) setIdValue(status.savedId);
    } catch (localError) {
      appendMainLog(`[${channel.title}] 本地检测命令失败，改用 Bridge 配置读取：${localError}\n`);
      detectionError = localError;

      const configResp = await configApi.read(OPENCLAW_CONFIG_PATH, {}).catch((error) => {
        appendMainLog(`[${channel.title}] 配置读取失败，继续检测本地插件包：${error}\n`);
        return { data: {} };
      });

      const packageResponses = await Promise.all(
        channel.packagePaths.map((packagePath) => configApi.read(packagePath, null).catch(() => ({ data: null }))),
      );

      const config = (configResp.data as any) || {};
      const savedChannel = getSavedChannelConfig(config, channel);
      if (savedChannel?.appId || savedChannel?.robotId || savedChannel?.clientId) {
        setIdValue(String(savedChannel.appId || savedChannel.robotId || savedChannel.clientId));
      }

      packageInstalled = packageResponses.some((resp) => isInstalledPackage(resp.data, channel.packageName));
      configured = configHasPlugin(config, channel);
      if (packageInstalled || extensionInstalled || configured) {
        detectionError = null;
      }
    }

    const summary = summarizePluginDetection(channel, packageInstalled, extensionInstalled, configured, detectionError || undefined);
    setPluginStatus(summary.status);
    setStatusMessage(summary.message);
    appendMainLog(`[${channel.title}] 插件检测：${summary.detected ? summary.message : '未检测到'}\n`);
    setChecking(false);
    return summary.detected;
  }, [appendMainLog, channel, runLocalPluginCheck]);

  useEffect(() => {
    checkPlugin().catch((error) => {
      setPluginStatus('error');
      setStatusMessage(`插件检测失败：${error?.message || error}`);
      setChecking(false);
    });
  }, [checkPlugin]);

  const spawnInstallStep = async (
    step: InstallStep,
    cwd: string | undefined,
    onCloseStep: (payload: TerminatedPayload) => void | Promise<void>,
  ) => {
    const options = makeCommandOptions(cwd);

    const attachListeners = (command: Command<string>) => {
      command.stdout.on('data', (data) => pushCommandLog(data));
      command.stderr.on('data', (data) => pushCommandLog(data));
      command.on('error', (error) => {
        setCommandRunning(false);
        setPluginStatus('error');
        setStatusMessage(`${step.label}启动失败：${error}`);
        pushCommandLog(`\n[error] ${error}\n`);
        showToast(`${step.label}启动失败`, 'error');
      });
      command.on('close', onCloseStep);
    };

    try {
      const command = Command.create(step.commandName, step.args, options);
      attachListeners(command);
      return await command.spawn();
    } catch (error) {
      pushCommandLog(`[fallback] ${step.commandName} 不可用，改用 ${step.fallbackCommandName}\n`);
      const fallback = Command.create(step.fallbackCommandName, step.args, options);
      attachListeners(fallback);
      return await fallback.spawn();
    }
  };

  const handleInstall = async () => {
    if (commandRunning) return;

    setCommandLog([]);
    setCommandRunning(true);
    stoppingRef.current = false;
    setStatusMessage('命令已启动，请在右侧查看实时输出');

    try {
      const cwd = await resolvePortableBasePath();

      const startStep = async (index: number): Promise<void> => {
        const step = channel.installSteps[index];
        setStatusMessage(`${step.label}运行中...`);
        pushCommandLog(`\n> ${step.displayCommand}\n`, false);

        const child = await spawnInstallStep(step, cwd, async (payload) => {
          childRef.current = null;
          pushCommandLog(`\n[exit] ${step.label} code=${payload.code ?? 'null'} signal=${payload.signal ?? 'null'}\n`);

          if (stoppingRef.current) {
            stoppingRef.current = false;
            setCommandRunning(false);
            setStatusMessage('命令已停止');
            return;
          }

          if (payload.code !== 0) {
            setCommandRunning(false);
            setPluginStatus('error');
            setStatusMessage(`${step.label}已退出，请查看右侧输出`);
            showToast(`${step.label}已退出，请查看输出`, 'error');
            return;
          }

          pushCommandLog(`[launcher] ${step.successMessage}\n`);
          const nextIndex = index + 1;

          if (nextIndex < channel.installSteps.length) {
            pushCommandLog('[launcher] 继续执行下一步，不会重启 OpenClaw 网关。\n');
            await startStep(nextIndex);
            return;
          }

          setCommandRunning(false);
          const detected = await checkPlugin();
          showToast(detected ? `${channel.title}安装流程完成` : '命令已结束，请确认扫码/绑定是否完成', detected ? 'success' : 'info');
        });

        childRef.current = child;
        pushCommandLog(`[launcher] ${step.label}已启动，PID ${child.pid}\n`);
        if (channel.key === 'weixin' || channel.key === 'feishu' || channel.key === 'dingtalk') {
          pushCommandLog('[launcher] 如果右侧出现二维码或网页登录链接，请直接扫码/打开链接完成绑定。\n');
        }
      };

      await startStep(0);
    } catch (error: any) {
      const message = error?.message || String(error);
      setCommandRunning(false);
      childRef.current = null;
      setPluginStatus('error');
      setStatusMessage(`安装失败：${message}`);
      pushCommandLog(`\n[launcher] 安装命令启动失败：${message}\n`);
      showToast(`${channel.title}安装失败：${message}`, 'error');
    }
  };

  const handleStopCommand = async () => {
    const child = childRef.current;
    if (!child) return;
    try {
      stoppingRef.current = true;
      await child.kill();
      pushCommandLog('\n[launcher] 已停止安装/绑定命令\n');
    } catch (error) {
      stoppingRef.current = false;
      pushCommandLog(`\n[launcher] 停止失败：${error}\n`);
    } finally {
      childRef.current = null;
      setCommandRunning(false);
    }
  };

  const handleSave = async () => {
    if (!idValue.trim() || !secretValue.trim()) {
      showToast(`请输入${channel.idLabel}和${channel.secretLabel}`, 'error');
      return;
    }

    try {
      const configResp = await configApi.read(OPENCLAW_CONFIG_PATH, {}).catch(() => ({ data: {} }));
      const data = (configResp.data as any) || {};
      data.channels = data.channels || {};

      const channelConfig = buildChannelConfig(channel, idValue.trim(), secretValue.trim());
      data.channels[channel.configKey] = channelConfig;
      if (channel.legacyConfigKey && channel.legacyConfigKey !== channel.configKey) {
        delete data.channels[channel.legacyConfigKey];
      }

      const plugins = data.plugins || {};
      plugins.allow = Array.isArray(plugins.allow) ? plugins.allow : [];
      if (!plugins.allow.includes(channel.pluginName)) plugins.allow.push(channel.pluginName);
      plugins.entries = plugins.entries || {};
      plugins.entries[channel.pluginName] = { ...(plugins.entries[channel.pluginName] || {}), enabled: true };
      data.plugins = plugins;

      await configApi.write(OPENCLAW_CONFIG_PATH, data);
      appendMainLog(`[${channel.title}] 通道配置已保存\n`);
      showToast(`${channel.title}配置已保存，重启核心服务后生效`, 'success');
      onClose();
    } catch (error: any) {
      showToast(`保存失败：${error?.error || error}`, 'error');
    }
  };

  const statusClass = useMemo(() => {
    if (pluginStatus === 'installed') return 'text-status-success';
    if (pluginStatus === 'error') return 'text-status-danger';
    return 'text-status-warning';
  }, [pluginStatus]);

  if (checking && pluginStatus === 'unknown') {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
        <div className="relative rounded-lg border border-border bg-surface/95 p-6 shadow-xl">
          <Loading text={statusMessage} />
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-5" onClick={onClose}>
      <div className="absolute inset-0 bg-black/72 backdrop-blur-sm" />
      <div
        className="relative grid max-h-[88vh] w-full max-w-5xl grid-cols-1 gap-5 overflow-hidden rounded-xl border border-border bg-surface/95 p-6 shadow-[0_24px_80px_rgba(0,0,0,0.55),0_0_32px_rgba(37,99,235,0.14)] lg:grid-cols-[minmax(0,0.9fr)_minmax(360px,1.1fr)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="min-w-0 overflow-y-auto pr-1">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold text-text">{channel.title}</h2>
              <p className="mt-2 text-sm leading-6 text-text-muted">{channel.description}</p>
            </div>
            <button onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text">&times;</button>
          </div>

          <div className="mb-5 rounded-xl border border-border bg-surface-alt/85 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className={`text-sm font-semibold ${statusClass}`}>{statusMessage}</p>
                <p className="mt-1 whitespace-pre-wrap break-all font-mono text-xs text-text-subtle">{commandSummary}</p>
              </div>
              <Button onClick={checkPlugin} variant="quiet" disabled={checking || commandRunning} className="shrink-0">
                重新检测
              </Button>
            </div>
          </div>

          <div className="mb-5 flex flex-wrap gap-3">
            <Button onClick={handleInstall} variant="primary" disabled={commandRunning}>
              {commandRunning ? '命令运行中...' : installed ? '重新执行安装/绑定' : `安装${channel.title}`}
            </Button>
            {commandRunning && (
              <Button onClick={handleStopCommand} variant="danger">
                停止命令
              </Button>
            )}
          </div>

          {channel.manualConfig ? (
            <div className="rounded-xl border border-border bg-surface-alt/70 p-4">
              <p className="text-sm font-semibold text-text">手动绑定配置</p>
              <p className="mt-1 text-xs leading-5 text-text-muted">
                安装插件后，填入开放平台中的应用信息即可写入 OpenClaw 配置。
              </p>
              {channel.docsUrl && (
                <a href={channel.docsUrl} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs font-medium text-accent hover:underline">
                  {channel.docsLabel}
                </a>
              )}

              <div className="mt-4 space-y-3">
                <div>
                  <FieldLabel text={channel.idLabel} />
                  <Input value={idValue} onChange={(event) => setIdValue(event.target.value)} placeholder={channel.idPlaceholder} />
                </div>
                <div>
                  <FieldLabel text={channel.secretLabel} />
                  <Input type="password" value={secretValue} onChange={(event) => setSecretValue(event.target.value)} placeholder={channel.secretPlaceholder} />
                </div>
                <div className="flex gap-3 pt-2">
                  <Button onClick={handleSave} variant="primary">保存配置</Button>
                  <Button onClick={onClose} variant="quiet">取消</Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-border bg-surface-alt/70 p-4">
              <p className="text-sm font-semibold text-text">扫码绑定</p>
              <p className="mt-1 text-xs leading-5 text-text-muted">
                {channel.title}通过命令行扫码授权完成绑定。点击安装后，请在右侧输出区扫描二维码，或按输出提示打开绑定链接。
              </p>
              <div className="mt-4 whitespace-pre-wrap rounded-lg border border-border bg-terminal-bg px-3 py-2 font-mono text-xs leading-5 text-terminal-text">
                {commandSummary}
              </div>
            </div>
          )}
        </div>

        <BotInstallConsole
          commandSummary={commandSummary}
          commandLog={commandLog}
          outputRef={outputRef}
          onClear={() => setCommandLog([])}
        />
      </div>
    </div>
  );
};

export const FeishuConfigDialog: React.FC<{ onClose: () => void }> = ({ onClose }) => (
  <BotConfigDialog channel={CHANNELS.feishu} onClose={onClose} />
);

export const WeixinConfigDialog: React.FC<{ onClose: () => void }> = ({ onClose }) => (
  <BotConfigDialog channel={CHANNELS.weixin} onClose={onClose} />
);

export const DingtalkConfigDialog: React.FC<{ onClose: () => void }> = ({ onClose }) => (
  <BotConfigDialog channel={CHANNELS.dingtalk} onClose={onClose} />
);
