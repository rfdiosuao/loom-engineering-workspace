export interface PhoneMatrixAccessDependencies {
  refreshLicense: () => Promise<void>;
  readLicense: () => { authorized: boolean };
  checkFeature: () => Promise<{ authorized: boolean }>;
}

export interface PhoneMatrixAccessResult {
  authorized: boolean;
  featureChecked: boolean;
}

export function createSingleFlight<T>(operation: () => Promise<T>): () => Promise<T> {
  let inFlight: Promise<T> | null = null;
  return () => {
    if (inFlight) return inFlight;
    const current = operation().finally(() => {
      if (inFlight === current) inFlight = null;
    });
    inFlight = current;
    return current;
  };
}

export async function resolvePhoneMatrixAccess(
  dependencies: PhoneMatrixAccessDependencies,
): Promise<PhoneMatrixAccessResult> {
  await dependencies.refreshLicense();
  if (!dependencies.readLicense().authorized) {
    return { authorized: false, featureChecked: false };
  }

  const feature = await dependencies.checkFeature();
  return {
    authorized: feature.authorized === true,
    featureChecked: true,
  };
}
