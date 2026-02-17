export type Eip6963ProviderInfo = {
  rdns: string;
  name: string;
  icon: string;
};

export type Eip6963ProviderDetail = {
  info: Eip6963ProviderInfo;
  provider: any;
};

type ProviderMap = Record<string, Eip6963ProviderDetail>;

const globalState = globalThis as typeof globalThis & {
  __rmEip6963Providers?: ProviderMap;
  __rmEip6963Listening?: boolean;
};

const getProviderMap = (): ProviderMap => {
  if (!globalState.__rmEip6963Providers) {
    globalState.__rmEip6963Providers = {};
  }
  return globalState.__rmEip6963Providers;
};

export const getEip6963Providers = (): ProviderMap => {
  return { ...getProviderMap() };
};

export const getEip6963ProviderByRdns = (rdns: string): Eip6963ProviderDetail | undefined => {
  return getProviderMap()[rdns];
};

export const registerEip6963Provider = (detail: Eip6963ProviderDetail) => {
  if (!detail?.info?.rdns) {
    return;
  }
  const providers = getProviderMap();
  if (!providers[detail.info.rdns]) {
    providers[detail.info.rdns] = detail;
  }
};

export const ensureEip6963Discovery = () => {
  if (typeof window === "undefined") {
    return;
  }
  if (globalState.__rmEip6963Listening) {
    return;
  }
  const handleProvider = (event: Event) => {
    const detail = (event as CustomEvent<Eip6963ProviderDetail>).detail;
    if (!detail?.info?.rdns) {
      return;
    }
    registerEip6963Provider(detail);
  };
  window.addEventListener("eip6963:announceProvider", handleProvider as EventListener);
  window.dispatchEvent(new Event("eip6963:requestProvider"));
  globalState.__rmEip6963Listening = true;
};
