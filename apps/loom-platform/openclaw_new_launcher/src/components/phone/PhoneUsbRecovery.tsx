import React from 'react';

import { showToast } from '../common';
import { phoneApi } from '../../services/api';

export function PhoneUsbRecovery() {
  React.useEffect(() => {
    let cancelled = false;

    const restoreSavedUsbPhones = async () => {
      try {
        try {
          await phoneApi.usbReconcile();
        } catch {
          // A pending cleanup is retried again on the next launcher start.
        }
        const snapshot = await phoneApi.config();
        const usbDevices = snapshot.devices.filter((device) => device.connectionMode === 'usb');
        const failedDevices: string[] = [];

        for (const device of usbDevices) {
          if (cancelled) return;
          try {
            await phoneApi.usbConnect({
              deviceId: device.id,
              confirmed: true,
            });
          } catch {
            failedDevices.push(device.name || device.id);
          }
        }

        if (!cancelled && failedDevices.length > 0) {
          showToast(
            `${failedDevices.length} 台已保存的 USB 手机未能自动恢复，请检查数据线和 USB 调试授权。`,
            'info',
          );
        }
      } catch {
        // Phone configuration is optional during early startup.
      }
    };

    void restoreSavedUsbPhones();
    return () => {
      cancelled = true;
    };
  }, []);

  return null;
}
