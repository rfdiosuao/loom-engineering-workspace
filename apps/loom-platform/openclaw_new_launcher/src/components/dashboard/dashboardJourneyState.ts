export type ComponentSnapshotProvenance = 'empty' | 'cache' | 'live';

interface VerificationTarget {
  ok?: boolean;
}

interface ConfigurationCheckResult {
  targets?: Record<string, VerificationTarget>;
}

const AGENT_WIRE_TARGETS: Record<string, string> = {
  'codex-desktop': 'codex',
  'claude-code': 'claude',
  opencode: 'opencode',
  'openclaw-companion': 'openclaw',
};

export function configurationCheckSucceeded(
  result: ConfigurationCheckResult | null,
  readyAgentIds: string[],
): boolean {
  if (result?.targets?.token?.ok !== true || readyAgentIds.length === 0) return false;
  return readyAgentIds.some((agentId) => {
    const target = AGENT_WIRE_TARGETS[agentId];
    return target ? result.targets?.[target]?.ok === true : agentId === 'hermes';
  });
}

export function resolveDashboardJourneyState(input: {
  loading: boolean;
  componentsProvenance: ComponentSnapshotProvenance;
  readyAgentIds: string[];
  hasConfiguredTextModel: boolean;
  configurationCheckPassed: boolean;
}) {
  const liveInstallReady = input.componentsProvenance === 'live' && input.readyAgentIds.length > 0;
  const liveModelReady = input.hasConfiguredTextModel;
  const canCheckNow = !input.loading && liveInstallReady && liveModelReady;
  const journeyReady = !input.loading && input.configurationCheckPassed;
  const activeStep = !liveInstallReady ? 1 : !liveModelReady ? 2 : !journeyReady ? 3 : 4;
  return {
    liveInstallReady,
    liveModelReady,
    canCheckNow,
    journeyReady,
    activeStep,
  };
}
