import React from 'react';
import { DashboardPage } from '../components/dashboard/DashboardPage';
import { TerminalPage } from '../components/terminal/TerminalPage';
import { LicensePage } from '../components/license/LicensePage';
import { ImagePage } from '../components/image/ImagePage';
import { VideoPage } from '../components/video/VideoPage';
import { StoryboardPage } from '../components/storyboard/StoryboardPage';
import { DiagnosticsPage } from '../components/diagnostics/DiagnosticsPage';
import { SkillsPage } from '../components/skills/SkillsPage';
import { PhoneControlPage } from '../components/phone/PhoneControlPage';
import { DesktopAgentPage } from '../components/desktop/DesktopAgentPage';
import { PublishPage } from '../components/publish/PublishPage';

const PAGE_COMPONENTS: Record<string, React.ComponentType> = {
  dashboard: DashboardPage,
  terminal: TerminalPage,
  license: LicensePage,
  image: ImagePage,
  video: VideoPage,
  storyboard: StoryboardPage,
  diagnostics: DiagnosticsPage,
  skills: SkillsPage,
  phone: PhoneControlPage,
  publish: PublishPage,
  desktop: DesktopAgentPage,
};

export function getFeaturePage(key: string): React.ComponentType {
  return PAGE_COMPONENTS[key] || TerminalPage;
}

export function renderFeaturePage(key: string): React.ReactNode {
  const Page = getFeaturePage(key);
  return <Page />;
}
