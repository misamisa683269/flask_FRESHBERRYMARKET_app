import { Container, getContainer } from "@cloudflare/containers";

export class FreshberryContainer extends Container {
  defaultPort = 8080;
  // デモ用途: アクセスが途絶えてもしばらく起動したままにする
  sleepAfter = "30m";
}

export default {
  async fetch(request: Request, env: { FRESHBERRY_CONTAINER: DurableObjectNamespace }): Promise<Response> {
    // 単一インスタンスに集約（SQLite / セッションを安定させる）
    const container = getContainer(env.FRESHBERRY_CONTAINER, "freshberry-main");
    return container.fetch(request);
  },
};
