import Redis from "ioredis";

const url = process.env.REDIS_URL || "redis://localhost:6379/0";

let _client: Redis | null = null;

export function getRedis(): Redis {
  if (!_client) {
    _client = new Redis(url, {
      connectTimeout: 2000,
      commandTimeout: 2000,
      lazyConnect: true,
      maxRetriesPerRequest: 1,
    });
    _client.on("error", () => {});
  }
  return _client;
}
