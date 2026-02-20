import Redis from "ioredis";

type RedisClient = Redis;

const globalForRedis = globalThis as typeof globalThis & { __rmRedis?: RedisClient };

export const getRedisClient = (): RedisClient | null => {
  const url = process.env.RM_REDIS_URL ?? process.env.REDIS_URL;
  if (!url) {
    return null;
  }
  if (!globalForRedis.__rmRedis) {
    globalForRedis.__rmRedis = new Redis(url, { maxRetriesPerRequest: 1, enableReadyCheck: false });
  }
  return globalForRedis.__rmRedis ?? null;
};
