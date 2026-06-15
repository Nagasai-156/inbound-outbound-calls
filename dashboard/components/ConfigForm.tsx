"use client";

import { useEffect, useState } from "react";
import {
  Card,
  Field,
  Select,
  Textarea,
  Range,
  Button,
  Check,
  Spinner,
  useToast,
} from "@/components/ui";
import {
  AGENT_TOOLS,
  LANGUAGES,
  LLM_MODELS,
  LLM_PROVIDERS,
  NUMERIC_FIELDS,
  speakersFor,
  STT_MODELS,
  TTS_PROVIDERS,
  USE_CASES,
  STT_MODES,
  TTS_MODELS,
  ttsModelsFor,
  llmModelsFor,
  PREVIEW_TEXT,
} from "@/lib/options";

type Cfg = Record<string, any>;

export default function ConfigForm() {
  const toast = useToast();
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [previewing, setPreviewing] = useState("");
  const [savingConfig, setSavingConfig] = useState(false);
  const [configName, setConfigName] = useState("");
  const [showSaveAs, setShowSaveAs] = useState(false);
  const [kbOptions, setKbOptions] = useState<{ value: string; label: string }[]>([
    { value: "", label: "— none (no KB grounding) —" },
  ]);

  async function saveAsConfig() {
    if (!configName.trim()) { toast("Enter a name", "bad"); return; }
    setSavingConfig(true);
    const r = await fetch("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...cfg, name: configName.trim() }),
    });
    const j = await r.json().catch(() => ({}));
    setSavingConfig(false);
    if (r.ok) {
      toast(`Config "${j.profile.name}" saved`, "ok");
      setConfigName("");
      setShowSaveAs(false);
    } else toast(j.error || "Failed", "bad");
  }

  async function preview(lang: string, speaker: string) {
    setPreviewing(lang + speaker);
    try {
      const r = await fetch("/api/tts/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: PREVIEW_TEXT[lang] || PREVIEW_TEXT.en,
          language: lang,
          speaker,
          model: cfg?.ttsModel || "bulbul:v2",
        }),
      });
      if (!r.ok) {
        toast("Preview failed: " + (await r.text()).slice(0, 80), "bad");
        return;
      }
      const blob = await r.blob();
      await new Audio(URL.createObjectURL(blob)).play();
    } catch (e: any) {
      toast("Preview error: " + e.message, "bad");
    } finally {
      setPreviewing("");
    }
  }

  // Sarvam speakers are per-MODEL, not per-language — the same voice
  // speaks te/hi/en. Expose ONE voice and mirror it to all three
  // language keys so per-call campaign overrides still resolve a voice
  // whatever language a call runs in.
  const setSpeaker = (v: string) => {
    setCfg((c) => ({
      ...(c as Cfg),
      ttsSpeakerTe: v,
      ttsSpeakerHi: v,
      ttsSpeakerEn: v,
    }));
    setDirty(true);
  };

  function VoiceField({ lang }: { lang: string }) {
    const current =
      cfg?.ttsSpeakerTe || cfg?.ttsSpeakerHi || cfg?.ttsSpeakerEn || "";
    const busy = previewing === lang + current;
    const langName =
      LANGUAGES.find((l) => l.value === lang)?.label || "the selected language";
    
    const voiceOptions = speakersFor(cfg?.ttsModel || "bulbul:v2");
    const hintText = `Preview plays in ${langName}. The same voice is used for every language this agent speaks.`;

    return (
      <Field
        label="Voice"
        hint={hintText}
      >
        <div className="flex gap-2">
          <div className="flex-1">
            <Select
              value={current}
              onChange={setSpeaker}
              options={voiceOptions}
            />
          </div>
          <Button
            type="button"
            className="btn-sm shrink-0"
            disabled={!!busy}
            onClick={() => preview(lang, current)}
          >
            {busy ? (
              <Spinner />
            ) : (
              <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5v14l11-7z" />
              </svg>
            )}{" "}
            Preview
          </Button>
        </div>
      </Field>
    );
  }

  useEffect(() => {
    fetch("/api/config")
      .then((r) => r.ok ? r.json() : ({} as any))
      .then((d) => {
        const c: Cfg = d.config || {};
        // Normalise any stale/invalid model+speaker combo on load so the
        // form is always in a Sarvam-valid state.
        const okModels = TTS_MODELS.map((m) => m.value);
        if (!okModels.includes(c.ttsModel)) c.ttsModel = "bulbul:v2";
        const valid = speakersFor(c.ttsModel).map((o) => o.value);
        for (const k of ["ttsSpeakerTe", "ttsSpeakerHi", "ttsSpeakerEn"]) {
          if (!valid.includes(c[k])) c[k] = valid[0];
        }
        // The old default was 2.5s = up to 2.5s of dead air after the
        // caller stops (the biggest perceived-lag source). If a stale
        // high value is persisted, surface the snappy recommended value
        // and flag the form dirty so one Save fixes it (visible, not
        // silent).
        if (Number(c.maxEndpointingDelay) > 1.2) {
          c.maxEndpointingDelay = 1;
          setDirty(true);
          toast(
            "Max endpointing delay was too high (slow replies) — set to " +
              "1.0s. Review and Save to apply.",
            "info"
          );
        }
        // Surface the provider that MATCHES the saved model so the
        // provider dropdown isn't misleading (the backend ignores the
        // stored llmProvider and routes off the model name, so we must
        // derive it from the model for a truthful UI).
        const lm = String(c.llmModel || "").toLowerCase();
        if (lm.startsWith("bedrock/")) c.llmProvider = "bedrock";
        else if (lm.startsWith("mistral/")) c.llmProvider = "mistral";
        else if (lm.startsWith("gemini/")) c.llmProvider = "gemini";
        else if (lm.startsWith("xai/")) c.llmProvider = "xai";
        else if (lm.startsWith("gpt-")) c.llmProvider = "openai";
        setCfg(c);
      });
  }, [toast]);

  // KB list for the default-KB selector (same source as the per-call /call
  // page). Inbound calls have no per-call KB picker, so this AgentConfig
  // value is the only way to ground them in a specific knowledge base.
  useEffect(() => {
    fetch("/api/knowledge-bases")
      .then((r) => (r.ok ? r.json() : { kbs: [] }))
      .then((d) =>
        setKbOptions([
          { value: "", label: "— none (no KB grounding) —" },
          ...(d.kbs || []).map((kb: any) => ({ value: kb.id, label: kb.name })),
        ])
      )
      .catch(() => {});
  }, []);

  const set = (k: string, v: any) => {
    setCfg((c) => ({ ...(c as Cfg), [k]: v }));
    setDirty(true);
  };
  // Changing the TTS model must remap speakers — each model only
  // accepts its own speaker set (Sarvam 400s on a mismatch).
  const setModel = (model: string) => {
    const valid = speakersFor(model).map((o) => o.value);
    setCfg((c) => {
      const n: Cfg = { ...(c as Cfg), ttsModel: model };
      for (const k of ["ttsSpeakerTe", "ttsSpeakerHi", "ttsSpeakerEn"]) {
        if (!valid.includes(n[k])) n[k] = valid[0];
      }
      return n;
    });
    setDirty(true);
  };
  const num = (k: string) => {
    const [label, min, max, step, hint] = NUMERIC_FIELDS[k];
    return (
      <Field key={k} label={label} hint={hint}>
        <Range
          value={Number(cfg?.[k] ?? min)}
          min={min}
          max={max}
          step={step}
          onChange={(v) => set(k, v)}
        />
      </Field>
    );
  };

  async function save() {
    setSaving(true);
    const r = await fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    setSaving(false);
    if (r.ok) {
      setDirty(false);
      toast("Saved — applies on the next call (~30s)", "ok");
    } else toast("Save failed", "bad");
  }

  async function regen() {
    toast("Regenerating content pools…", "info");
    const r = await fetch("/api/content", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ business: cfg?.businessDescription || "", n: 12 }),
    });
    toast(
      r.ok ? "Content generation started (LLM → Redis)" : "Could not start",
      r.ok ? "ok" : "bad"
    );
  }

  if (!cfg)
    return (
      <div className="flex items-center gap-2 text-[var(--muted)]">
        <Spinner /> Loading configuration…
      </div>
    );

  return (
    <div className="space-y-5 pb-24">
      <Card
        title="Language & voice"
        desc="Pick the language this agent speaks, then its voice. Campaigns can override the language per call."
      >
        <div className="grid gap-5">
          <Field
            label="TTS Provider"
            hint="Sarvam Bulbul = proven Telugu quality (460ms)"
          >
            <Select
              value={cfg.ttsProvider || "sarvam"}
              onChange={(v) => {
                set("ttsProvider", v);
                // Only Sarvam now — keep model/speaker on the Sarvam default.
                const defaultModel = "bulbul:v2";
                setSpeaker(speakersFor(defaultModel)[0].value);
                set("ttsModel", defaultModel);
              }}
              options={TTS_PROVIDERS}
            />
          </Field>
          <Field
            label="Language"
            hint="The agent listens (STT) and speaks (TTS) in THIS language for every call, unless a campaign / single-call sets its own."
          >
            <Select
              value={cfg.defaultLanguage}
              onChange={(v) => set("defaultLanguage", v)}
              options={LANGUAGES}
            />
          </Field>
          <Field
            label="Auto-mirror caller's language"
            hint="When ON: from turn 2 onward, the agent replies in whatever language the caller's most recent full sentence used (Telugu / Hindi / English / code-mix). The opener still uses the default language above. When OFF: the agent stays in the default language throughout."
          >
            <Check
              checked={Boolean(cfg.autoMirrorLanguage)}
              onChange={(v) => set("autoMirrorLanguage", v)}
              label={cfg.autoMirrorLanguage ? "On — mirror caller" : "Off — stay in default language"}
            />
          </Field>
          <div className="grid md:grid-cols-2 gap-5">
            <Field label="TTS model">
              <Select
                value={cfg.ttsModel}
                onChange={setModel}
                options={ttsModelsFor(cfg.ttsProvider || "sarvam")}
              />
            </Field>
            {num("ttsPace")}
            {num("ttsPaceTe")}
            {num("ttsPaceHi")}
            {num("ttsPaceEn")}
          </div>
          <VoiceField lang={cfg.defaultLanguage || "te"} />
        </div>
      </Card>

      <Card
        title="Turn-taking & latency"
        desc="Tuned for natural Telugu/Hindi pauses and barge-in feel."
      >
        <div className="grid md:grid-cols-2 gap-5">
          {[
            "minEndpointingDelay",
            "maxEndpointingDelay",
            "teluguMinEndpointingDelay",
            "minInterruptionDuration",
            "fillerLatencyThreshold",
            "fillerMinSttConfidence",
          ].map(num)}
        </div>
      </Card>

      <Card
        title="Persona & content"
        desc="Leave persona blank to use the built-in support/sales personas."
        actions={
          <Button onClick={regen} variant="ghost">
            Regenerate content pools
          </Button>
        }
      >
        <div className="grid gap-5">
          <Field
            label="Business description"
            hint="Used when generating fillers / canned replies"
          >
            <Textarea
              value={cfg.businessDescription}
              onChange={(e) => set("businessDescription", e.target.value)}
              placeholder="e.g. Acme food delivery — order tracking, refunds, payments"
            />
          </Field>
          <div className="grid md:grid-cols-2 gap-5">
            <Field label="Inbound persona override">
              <Textarea
                value={cfg.inboundPersona}
                onChange={(e) => set("inboundPersona", e.target.value)}
              />
            </Field>
            <Field label="Outbound persona override">
              <Textarea
                value={cfg.outboundPersona}
                onChange={(e) => set("outboundPersona", e.target.value)}
              />
            </Field>
          </div>
          <Field
            label="Use-case (inbound / global default)"
            hint="Drives the scoped behaviour block + which tools the agent gets for INBOUND calls (campaigns set their own per-campaign). Booking tools only for appointment-family; everything else (incl. Custom) cannot book."
          >
            <Select
              value={cfg.useCaseType || "custom"}
              onChange={(v) => set("useCaseType", v)}
              options={USE_CASES}
            />
          </Field>
          <Field
            label="Enabled tools (override)"
            hint="Empty = let the Use-case above pick tools automatically (recommended). Tick any to expose ONLY those tools (kb_search + end_call always included). Useful for businesses that mix patterns — e.g. salon = appointments + orders."
          >
            <div className="grid sm:grid-cols-2 gap-2">
              {AGENT_TOOLS.map((t) => {
                const selected = new Set<string>(
                  String(cfg.enabledTools || "")
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean)
                );
                const on = selected.has(t.value);
                return (
                  <label
                    key={t.value}
                    className="flex items-start gap-2 text-[13px] cursor-pointer p-2 rounded-[var(--radius-sm)] hover:bg-[var(--bg-soft)]"
                    title={t.hint}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      className="mt-1 accent-[var(--accent)]"
                      onChange={() => {
                        if (on) selected.delete(t.value);
                        else selected.add(t.value);
                        set(
                          "enabledTools",
                          Array.from(selected).join(","),
                        );
                      }}
                    />
                    <span>
                      <span className="text-[var(--txt)]">{t.label}</span>
                      <span className="block text-[12px] text-[var(--muted)]">
                        {t.hint}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          </Field>
          <Field
            label="Style example override (few-shot)"
            hint="Blank = neutral built-in. Put a short sample dialogue in YOUR language/domain to steer tone & code-mix. Campaign script can also carry its own."
          >
            <Textarea
              value={cfg.styleExamples}
              onChange={(e) => set("styleExamples", e.target.value)}
              placeholder={
                'e.g. You: "నమస్కారం సర్, ... call చేశా — time ఉందా?"\n' +
                'Caller: "ఎందుకు?"\nYou: "..." (answer first, then progress)'
              }
            />
          </Field>
        </div>
      </Card>

      <Card
        title="Appointment hours"
        desc="The grid the agent can book. Set to YOUR business hours — clinic 9-18, salon 10-20, gym 6-22. Saved here so the AI never offers a slot outside hours and the prompt's working-hours block stays in sync."
      >
        <div className="grid md:grid-cols-3 gap-5">
          {num("apptOpenHour")}
          {num("apptCloseHour")}
          {num("apptSlotMin")}
        </div>
        <div className="mt-5">
          <Field
            label="Open weekdays"
            hint="Comma-separated indices, Mon=0 … Sun=6. Default Mon-Sat = 0,1,2,3,4,5. For a 7-day business use 0,1,2,3,4,5,6."
          >
            <Textarea
              value={cfg.apptOpenWeekdays ?? "0,1,2,3,4,5"}
              onChange={(e) => set("apptOpenWeekdays", e.target.value)}
              placeholder="0,1,2,3,4,5"
            />
          </Field>
        </div>
      </Card>

      <Card title="Model & knowledge base">
        <div className="grid md:grid-cols-2 gap-5">
          <Field
            label="LLM Provider"
            hint="OpenAI = reliable US region | Mistral = fast small models"
          >
            <Select
              value={cfg.llmProvider || "openai"}
              onChange={(v) => {
                // Provider change must ALSO switch the model — the backend
                // routes purely off the MODEL NAME (llmProvider isn't even
                // persisted), so leaving a stale model means the provider
                // pick silently does nothing. Auto-select the first model
                // that belongs to the chosen provider so the selection is
                // truly dynamic: pick provider → valid model → Save works.
                const first = llmModelsFor(v)[0];
                setCfg((c) => ({
                  ...(c as Cfg),
                  llmProvider: v,
                  ...(first ? { llmModel: first.value } : {}),
                }));
                setDirty(true);
              }}
              options={LLM_PROVIDERS}
            />
          </Field>
          <Field label="LLM model">
            <Select
              value={cfg.llmModel}
              onChange={(v) => set("llmModel", v)}
              options={llmModelsFor(cfg.llmProvider || "openai")}
            />
          </Field>
          {num("llmTemperature")}
          <Field label="STT model">
            <Select
              value={cfg.sttModel}
              onChange={(v) => set("sttModel", v)}
              options={STT_MODELS}
            />
          </Field>
          <Field label="STT mode">
            <Select
              value={cfg.sttMode}
              onChange={(v) => set("sttMode", v)}
              options={STT_MODES}
            />
          </Field>
          {num("memoryMaxTurns")}
          {num("llmPromptMaxTokens")}
          {num("cacheMinSimilarity")}
          <Field
            label="Cache TTS audio (instant fixed phrases)"
            hint="When ON: fillers, canned replies (greeting/thanks/bye/repeat) and repeated cache answers replay pre-rendered audio instead of re-synthesising — removes ~270-460ms TTS first-byte latency on those turns. Validate on one live call (phrases should sound identical and barge-in still cuts them) before relying on it."
          >
            <Check
              checked={Boolean(cfg.ttsAudioCache)}
              onChange={(v) => set("ttsAudioCache", v)}
              label={cfg.ttsAudioCache ? "On — replay cached audio" : "Off — always synthesise"}
            />
          </Field>
          <Field
            label="Default Knowledge Base"
            hint="Used for inbound calls and any outbound call/campaign that doesn't pick its own KB. Empty = the agent answers without KB grounding."
          >
            <Select
              value={cfg.kbVectorStoreId ?? ""}
              onChange={(v) => set("kbVectorStoreId", v)}
              options={kbOptions}
            />
          </Field>
        </div>
        <p className="text-[12px] text-[var(--muted)] mt-4">
          Knowledge base runs on Supabase pgvector — manage documents
          under <span className="text-[var(--txt)]">Knowledge Base</span>.
        </p>
      </Card>

      <div className="fixed bottom-0 left-0 lg:left-[252px] right-0 border-t border-[var(--line)] bg-[var(--bg)]/90 backdrop-blur px-4 sm:px-6 lg:px-8 py-3 flex items-center gap-3 z-30">
        <Button variant="primary" onClick={save} disabled={saving || !dirty}>
          {saving ? <Spinner /> : null}
          {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
        </Button>

        {showSaveAs ? (
          <div className="flex items-center gap-2">
            <input
              autoFocus
              className="border border-[var(--line)] rounded-[var(--radius-sm)] px-2.5 py-1.5 text-[13px] bg-[var(--bg)] text-[var(--txt)] w-44 focus:outline-none focus:border-[var(--accent)]"
              placeholder="Config name…"
              value={configName}
              onChange={(e) => setConfigName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") saveAsConfig(); if (e.key === "Escape") setShowSaveAs(false); }}
            />
            <Button onClick={saveAsConfig} disabled={savingConfig}>
              {savingConfig ? <Spinner /> : "Save"}
            </Button>
            <button onClick={() => setShowSaveAs(false)} className="text-[var(--muted)] text-[13px] hover:text-[var(--txt)]">✕</button>
          </div>
        ) : (
          <Button variant="ghost" onClick={() => setShowSaveAs(true)}>
            Save as config…
          </Button>
        )}

        <span className="text-[12px] text-[var(--muted)] hidden sm:block">
          Applied at the start of the next call (Redis-cached ~30s).
        </span>
      </div>
    </div>
  );
}
