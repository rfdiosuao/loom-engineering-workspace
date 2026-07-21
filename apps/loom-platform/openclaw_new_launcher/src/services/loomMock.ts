import type { AccountSnapshot, MatrixStatusSnapshot, WireSnapshot } from './loomContracts';

export const loomMock = {
  account: {
    loggedIn: false,
    models: { text: [], image: [], video: [] },
    selectedModels: {},
  } satisfies AccountSnapshot,
  wire: {
    ok: false,
    managedBy: 'mock',
    models: {},
    modelLists: {},
  } satisfies WireSnapshot,
  matrix: {
    schema: 'loom.matrix.v1',
    devices: [],
    summary: { total: 0, online: 0, busy: 0, failed: 0 },
  } satisfies MatrixStatusSnapshot,
};
