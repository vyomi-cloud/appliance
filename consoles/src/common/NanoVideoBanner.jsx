import { useEffect, useRef } from "react";

// Nano only: the "How Nano <cloud> works" banner (wasm/nano-video.js, a plain script the Nano shell loads).
// Renders nothing on the offline appliance, where window.vyVideoBanner is never defined.
export default function NanoVideoBanner({ cloud }) {
  const host = useRef(null);
  useEffect(() => {
    const el = host.current;
    if (!el || typeof window.vyVideoBanner !== "function") return undefined;
    const banner = window.vyVideoBanner(cloud);
    el.appendChild(banner);
    return () => { banner.remove(); };
  }, [cloud]);
  return <div ref={host} className="vy-nano-video" />;
}
