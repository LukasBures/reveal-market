const store = new Map<string, string>();

const AsyncStorage = {
  async getItem(key: string): Promise<string | null> {
    return store.has(key) ? store.get(key)! : null;
  },
  async setItem(key: string, value: string): Promise<void> {
    store.set(key, value);
  },
  async clear(): Promise<void> {
    store.clear();
  },
};

export default AsyncStorage;
