import React, { Suspense } from 'react';
import { DashboardPage } from '../components/dashboard/DashboardPage';
import { Loading } from '../components/common';
import { PhoneMatrixAccessGate } from '../components/license/PhoneMatrixAccessGate';

// Only the default landing page (dashboard) is eager. The primary installer
// surface stays intentionally small: account, agent install, runtime, diagnostics.
function lazyNamed(
  loader: () => Promise<Record<string, unknown>>,
  name: string,
): React.ComponentType {
  return React.lazy(async () => ({ default: (await loader())[name] as React.ComponentType }));
}

const TerminalPage = lazyNamed(() => import('../components/terminal/TerminalPage'), 'TerminalPage');
const AgentInstallerPage = lazyNamed(() => import('../components/agents/AgentInstallerPage'), 'AgentInstallerPage');
const AgentWorkbenchPage = lazyNamed(() => import('../components/agent/AgentWorkbenchPage'), 'AgentWorkbenchPage');
const CreativeMediaPage = lazyNamed(() => import('../components/creative/CreativeMediaPage'), 'CreativeMediaPage');
const AcquisitionWorkbenchPage = lazyNamed(() => import('../components/acquisition/AcquisitionWorkbenchPage'), 'AcquisitionWorkbenchPage');
const PhoneDemoPage = lazyNamed(() => import('../components/phone/PhoneDemoPage'), 'PhoneDemoPage');
const MatrixWorkbenchPage = lazyNamed(() => import('../components/matrix/MatrixWorkbenchPage'), 'MatrixWorkbenchPage');
const CapabilityCenterPage = lazyNamed(() => import('../components/capabilities/CapabilityCenterPage'), 'CapabilityCenterPage');
const LicensePage = lazyNamed(() => import('../components/license/LicensePage'), 'LicensePage');
const ModelsPage = lazyNamed(() => import('../components/models/ModelsPage'), 'ModelsPage');
const DiagnosticsPage = lazyNamed(() => import('../components/diagnostics/DiagnosticsPage'), 'DiagnosticsPage');
const SettingsPage = lazyNamed(() => import('../components/settings/SettingsPage'), 'SettingsPage');
const AgentAccessPage = lazyNamed(() => import('../components/agentAccess/AgentAccessPage'), 'AgentAccessPage');

const PhoneConnectionPage = () => (
  <PhoneMatrixAccessGate>
    <PhoneDemoPage />
  </PhoneMatrixAccessGate>
);

const GuardedMatrixWorkbenchPage = () => (
  <PhoneMatrixAccessGate>
    <MatrixWorkbenchPage />
  </PhoneMatrixAccessGate>
);

const PAGE_COMPONENTS: Record<string, React.ComponentType> = {
  dashboard: DashboardPage,
  agents: AgentInstallerPage,
  agent: AgentWorkbenchPage,
  creative: CreativeMediaPage,
  acquisition: AcquisitionWorkbenchPage,
  phone: PhoneConnectionPage,
  workbench: GuardedMatrixWorkbenchPage,
  capabilities: CapabilityCenterPage,
  terminal: TerminalPage,
  license: LicensePage,
  models: ModelsPage,
  agentAccess: AgentAccessPage,
  diagnostics: DiagnosticsPage,
  settings: SettingsPage,
};

export function getFeaturePage(key: string): React.ComponentType {
  return PAGE_COMPONENTS[key] || DashboardPage;
}

export function renderFeaturePage(key: string): React.ReactNode {
  const Page = getFeaturePage(key);
  return (
    <Suspense fallback={<div className="flex h-full w-full items-center justify-center"><Loading /></div>}>
      <Page />
    </Suspense>
  );
}
