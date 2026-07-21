import React from 'react';
import { Shell } from './components/Shell';
import { SetupGate } from './components/SetupGate';
import { usePreviewStore } from './store/appStore';
import type { RouteKey } from './types';
import { DashboardPage } from './pages/DashboardPage';

const ServicePage = React.lazy(() => import('./pages/ServicePage').then((module) => ({ default: module.ServicePage })));
const AgentsPage = React.lazy(() => import('./pages/AgentsPage').then((module) => ({ default: module.AgentsPage })));
const LicensePage = React.lazy(() => import('./pages/LicensePage').then((module) => ({ default: module.LicensePage })));
const IntegrationsPage = React.lazy(() => import('./pages/IntegrationsPage').then((module) => ({ default: module.IntegrationsPage })));
const StudioPage = React.lazy(() => import('./pages/StudioPage').then((module) => ({ default: module.StudioPage })));
const PhonePage = React.lazy(() => import('./pages/PhonePage').then((module) => ({ default: module.PhonePage })));
const DesktopPage = React.lazy(() => import('./pages/DesktopPage').then((module) => ({ default: module.DesktopPage })));
const SkillsPage = React.lazy(() => import('./pages/SkillsPage').then((module) => ({ default: module.SkillsPage })));
const DiagnosticsPage = React.lazy(() => import('./pages/DiagnosticsPage').then((module) => ({ default: module.DiagnosticsPage })));
const SettingsPage = React.lazy(() => import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })));

const ROUTE_TITLES: Record<RouteKey, string> = {
  agents: '智能体',
  dashboard: '安装首页',
  service: '核心服务',
  license: '账号 / 授权',
  integrations: '平台对接',
  studio: '图像 / 视频',
  phone: '手机控制',
  desktop: '桌面 RPA',
  skills: 'Skills',
  diagnostics: '环境检测',
  settings: '统一设置',
};

function parseHash(): RouteKey {
  const value = window.location.hash.replace(/^#\/?/, '');
  const candidate = value.split('/')[0] as RouteKey;
  return candidate && candidate in ROUTE_TITLES ? candidate : 'dashboard';
}

function PageRouter() {
  const route = usePreviewStore((state) => state.route);
  let page: React.ReactNode;

  switch (route) {
    case 'agents':
      page = <AgentsPage />;
      break;
    case 'service':
      page = <ServicePage />;
      break;
    case 'license':
      page = <LicensePage />;
      break;
    case 'integrations':
      page = <IntegrationsPage />;
      break;
    case 'studio':
      page = <StudioPage />;
      break;
    case 'phone':
      page = <PhonePage />;
      break;
    case 'desktop':
      page = <DesktopPage />;
      break;
    case 'skills':
      page = <SkillsPage />;
      break;
    case 'diagnostics':
      page = <DiagnosticsPage />;
      break;
    case 'settings':
      page = <SettingsPage />;
      break;
    case 'dashboard':
    default:
      page = <DashboardPage />;
  }

  return (
    <React.Suspense fallback={<div className="panel-loading route-loading">Loading page...</div>}>
      {page}
    </React.Suspense>
  );
}

export default function App() {
  const route = usePreviewStore((state) => state.route);
  const navigate = usePreviewStore((state) => state.navigate);
  const [initialized, setInitialized] = React.useState(false);

  React.useEffect(() => {
    const initial = parseHash();
    navigate(initial);
    setInitialized(true);
  }, [navigate]);

  React.useEffect(() => {
    const onHashChange = () => {
      navigate(parseHash());
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, [navigate]);

  React.useEffect(() => {
    if (!initialized) return;
    if (window.location.hash.replace(/^#\/?/, '').split('/')[0] !== route) {
      window.history.replaceState(null, '', `#/${route}`);
    }
    document.title = `OpenClaw - ${ROUTE_TITLES[route]}`;
  }, [route, initialized]);

  return (
    <>
      <Shell>
        <PageRouter />
      </Shell>
      <SetupGate />
    </>
  );
}
