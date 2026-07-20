export type CircleSdkResult = {
  userToken: string;
  encryptionKey: string;
  refreshToken?: string;
  userId?: string;
  userID?: string;
};

export type CircleSdk = {
  getDeviceId: () => Promise<string>;
  updateConfigs: (config: Record<string, unknown>) => void;
  performLogin: (provider: unknown) => Promise<void>;
  verifyOtp: () => void;
  setAuthentication: (auth: { userToken: string; encryptionKey: string }) => void;
  execute: (challengeId: string, callback: (error?: unknown, result?: unknown) => void) => void;
};

export type CircleSdkModule = {
  W3SSdk?: new (
    config: Record<string, unknown>,
    callback: (error: unknown, result: unknown) => void,
  ) => CircleSdk;
};
