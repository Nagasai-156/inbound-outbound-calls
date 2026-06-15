"use client";

import { useEffect, useRef, useState } from "react";
import { Room, RoomEvent, RemoteTrack } from "livekit-client";
import { createClient } from "@/lib/supabase/client";
import { Card, Button, Badge, useToast } from "@/components/ui";

type Turn = { role: string; text: string };

export default function TestClient() {
  const toast = useToast();
  const [status, setStatus] = useState("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [speaking, setSpeaking] = useState(false);
  const roomRef = useRef<Room | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const channelRef = useRef<ReturnType<ReturnType<typeof createClient>["channel"]> | null>(null);

  // ── Voice-reactive visualizer wiring ───────────────────────────
  const orbRef = useRef<HTMLDivElement | null>(null);
  const barsRef = useRef<HTMLDivElement | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);

  function startVisualizer(track: RemoteTrack) {
    try {
      const Ctx =
        (window as any).AudioContext || (window as any).webkitAudioContext;
      const ctx: AudioContext = new Ctx();
      const stream = new MediaStream([track.mediaStreamTrack]);
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 128;
      analyser.smoothingTimeConstant = 0.78;
      src.connect(analyser);
      audioCtxRef.current = ctx;
      analyserRef.current = analyser;

      const freq = new Uint8Array(analyser.frequencyBinCount);
      const NB = 7; // number of bars

      const loop = () => {
        const a = analyserRef.current;
        if (!a) return;
        a.getByteFrequencyData(freq);
        // Overall volume (0..1)
        let sum = 0;
        for (let i = 0; i < freq.length; i++) sum += freq[i];
        const level = Math.min(1, sum / freq.length / 140);

        if (orbRef.current) {
          const scale = 1 + level * 0.55;
          orbRef.current.style.transform = `scale(${scale.toFixed(3)})`;
          orbRef.current.style.boxShadow = `0 0 ${
            20 + level * 60
          }px ${6 + level * 26}px rgba(2,132,199,${0.18 + level * 0.4})`;
        }
        // Per-bar heights from frequency bands
        const bars = barsRef.current?.children;
        if (bars) {
          const band = Math.floor(freq.length / NB);
          for (let b = 0; b < NB; b++) {
            let bs = 0;
            for (let i = 0; i < band; i++) bs += freq[b * band + i];
            const h = 8 + Math.min(1, bs / band / 150) * 46;
            (bars[b] as HTMLElement).style.height = `${h.toFixed(0)}px`;
          }
        }
        setSpeaking(level > 0.06);
        rafRef.current = requestAnimationFrame(loop);
      };
      rafRef.current = requestAnimationFrame(loop);
    } catch {
      /* visualizer is best-effort — never break the call */
    }
  }

  function stopVisualizer() {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    analyserRef.current = null;
    try {
      audioCtxRef.current?.close();
    } catch {}
    audioCtxRef.current = null;
    setSpeaking(false);
    if (orbRef.current) {
      orbRef.current.style.transform = "scale(1)";
      orbRef.current.style.boxShadow = "0 0 20px 6px rgba(2,132,199,.18)";
    }
  }

  function subscribe(callId: string) {
    const sb = createClient();
    if (channelRef.current) {
      sb.removeChannel(channelRef.current);
      channelRef.current = null;
    }
    const ch = sb
      .channel(`test-${callId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "voiceai",
          table: "Transcript",
          filter: `callId=eq.${callId}`,
        },
        (p: any) =>
          setTurns((t) => [...t, { role: p.new.role, text: p.new.text }])
      )
      .subscribe();
    channelRef.current = ch;
    return ch;
  }

  async function start() {
    setStatus("connecting…");
    setTurns([]);
    try {
      const res = await fetch("/api/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identity: "web-" + Date.now() }),
      });
      if (!res.ok) throw new Error(await res.text());
      const { url, token, room } = await res.json();
      const r = new Room({ adaptiveStream: true });
      r.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === "audio" && audioRef.current) {
          track.attach(audioRef.current);
          startVisualizer(track);
        }
      });
      r.on(RoomEvent.Disconnected, () => {
        stopVisualizer();
        setStatus("idle");
      });
      await r.connect(url, token);
      await r.localParticipant.setMicrophoneEnabled(true);
      roomRef.current = r;
      subscribe(room);
      setStatus("● live");
      toast("Connected — start speaking", "ok");
    } catch (e: any) {
      setStatus("error");
      toast("Could not start: " + e.message, "bad");
    }
  }

  function stop() {
    stopVisualizer();
    roomRef.current?.disconnect();
    roomRef.current = null;
    if (channelRef.current) {
      createClient().removeChannel(channelRef.current);
      channelRef.current = null;
    }
    setStatus("idle");
  }

  useEffect(() => {
    return () => {
      stopVisualizer();
      roomRef.current?.disconnect();
      if (channelRef.current) {
        createClient().removeChannel(channelRef.current);
        channelRef.current = null;
      }
    };
  }, []);

  const live = status === "● live";

  return (
    <Card
      title="Browser test call"
      actions={<Badge tone={live ? "ok" : "default"}>{status}</Badge>}
    >
      {/* ── Voice visualizer ───────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 18,
          padding: "30px 0 26px",
          minHeight: 200,
        }}
      >
        <div style={{ position: "relative", width: 120, height: 120 }}>
          {/* pulsing rings (only animate when live) */}
          {live && (
            <>
              <span className="vz-ring" style={{ animationDelay: "0s" }} />
              <span className="vz-ring" style={{ animationDelay: ".9s" }} />
              <span className="vz-ring" style={{ animationDelay: "1.8s" }} />
            </>
          )}
          {/* core orb (audio-reactive scale/glow) */}
          <div
            ref={orbRef}
            style={{
              position: "absolute",
              inset: 24,
              borderRadius: "50%",
              background:
                "radial-gradient(circle at 35% 30%, #38bdf8, #0284c7 70%)",
              boxShadow: "0 0 20px 6px rgba(2,132,199,.18)",
              transition: "transform .06s linear",
              display: "grid",
              placeItems: "center",
            }}
          >
            <svg
              width="26"
              height="26"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#fff"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="9" y="2" width="6" height="12" rx="3" />
              <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
            </svg>
          </div>
        </div>

        {/* frequency bars */}
        <div
          ref={barsRef}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            height: 56,
          }}
        >
          {Array.from({ length: 7 }).map((_, i) => (
            <div
              key={i}
              style={{
                width: 5,
                height: 8,
                borderRadius: 3,
                background: live
                  ? "linear-gradient(#38bdf8,#0284c7)"
                  : "var(--line)",
                transition: "height .08s linear",
              }}
            />
          ))}
        </div>

        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: speaking
              ? "#0284c7"
              : live
              ? "var(--muted)"
              : "var(--faint)",
            minHeight: 18,
            transition: "color .2s",
          }}
        >
          {!live
            ? "Tap Start and speak — no phone needed"
            : speaking
            ? "🔊 Agent speaking…"
            : "🎙️ Listening… speak in Telugu / Hindi / English"}
        </div>
      </div>

      <div className="flex items-center justify-center gap-3 mb-4">
        {!live ? (
          <Button variant="primary" onClick={start}>
            Start call
          </Button>
        ) : (
          <Button onClick={stop}>Hang up</Button>
        )}
      </div>

      {/* transcript */}
      <div className="flex flex-col gap-2 max-h-[42vh] overflow-auto">
        {turns.map((t, i) => (
          <div
            key={i}
            className={
              "px-4 py-2.5 rounded-2xl max-w-[78%] border text-[14px] shadow-sm " +
              (t.role === "user"
                ? "self-end bg-[var(--accent-soft)] border-[rgba(79,70,229,.22)] rounded-br-md"
                : "self-start bg-[#fbfbfc] border-[var(--line)] rounded-bl-md")
            }
          >
            <div
              className={
                "text-[11px] font-semibold mb-0.5 " +
                (t.role === "user"
                  ? "text-[var(--accent-2)]"
                  : "text-[var(--muted)]")
              }
            >
              {t.role === "user" ? "You" : "Agent"}
            </div>
            {t.text}
          </div>
        ))}
      </div>

      <audio ref={audioRef} autoPlay />

      <style jsx>{`
        .vz-ring {
          position: absolute;
          inset: 24px;
          border-radius: 50%;
          border: 2px solid rgba(2, 132, 199, 0.4);
          animation: vzpulse 2.7s ease-out infinite;
        }
        @keyframes vzpulse {
          0% {
            transform: scale(1);
            opacity: 0.5;
          }
          100% {
            transform: scale(2.1);
            opacity: 0;
          }
        }
      `}</style>
    </Card>
  );
}
