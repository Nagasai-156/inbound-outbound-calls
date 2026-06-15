"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Card,
  Field,
  Input,
  Select,
  Textarea,
  Button,
  Spinner,
  useToast,
  PageHeader,
} from "@/components/ui";
import { LANGUAGES, TTS_MODELS, speakersFor, USE_CASES } from "@/lib/options";

export default function CallPage() {
  const toast = useToast();
  const [callerIds, setCallerIds] = useState<{ value: string; label: string }[]>([]);
  const [callerId, setCallerId] = useState("");
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [lang, setLang] = useState("");
  const [script, setScript] = useState("");
  const [voiceModel, setVoiceModel] = useState("");
  const [voiceSpeaker, setVoiceSpeaker] = useState("");
  const [useCaseType, setUseCaseType] = useState("custom");
  const [businessDescription, setBusinessDescription] = useState("");
  const [styleExamples, setStyleExamples] = useState("");
  const [kbVectorStoreId, setKbVectorStoreId] = useState("");
  const [kbOptions, setKbOptions] = useState<{ value: string; label: string }[]>([{ value: "", label: "— none (use global KB) —" }]);
  const [busy, setBusy] = useState(false);
  const [room, setRoom] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    fetch("/api/numbers")
      .then((r) => r.ok ? r.json() : { numbers: [] })
      .then((d) => {
        const cs = (d.numbers || [])
          .filter((n: any) => n.outbound && n.active)
          .map((n: any) => ({
            value: n.e164,
            label: `${n.e164}${n.label ? " · " + n.label : ""}`,
          }));
        setCallerIds(cs);
        if (cs[0]) setCallerId(cs[0].value);
      }).catch(() => {});
    fetch("/api/knowledge-bases")
      .then((r) => r.ok ? r.json() : { kbs: [] })
      .then((d) => setKbOptions([
        { value: "", label: "— none (use global KB) —" },
        ...(d.kbs || []).map((kb: any) => ({ value: kb.id, label: kb.name })),
      ])).catch(() => {});
    fetch("/api/config")
      .then((r) => r.ok ? r.json() : ({} as any))
      .then((d) => {
        const dl = d?.config?.defaultLanguage;
        if (dl === "te" || dl === "hi" || dl === "en") setLang(dl);
      })
      .catch(() => {});
  }, []);

  async function dial() {
    if (!/^\+\d{8,15}$/.test(phone.trim())) {
      toast("Enter a valid number, e.g. +9198XXXXXXXX", "bad");
      return;
    }
    setBusy(true);
    setRoom("");
    const r = await fetch("/api/outbound", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phone_number: phone.trim(),
        caller_id: callerId,
        name,
        language: lang || "te",
        script,
        voice_model: voiceModel,
        voice_speaker: voiceSpeaker,
        use_case: useCaseType,
        business_description: businessDescription,
        style_examples: styleExamples,
        kb_vector_store_id: kbVectorStoreId,
      }),
    });
    const j = await r.json().catch(() => ({}));
    setBusy(false);
    if (r.ok) {
      setRoom(j.room);
      toast("Dialing… the agent will talk to this script", "ok");
    } else toast(j.detail || j.error || "Dial failed", "bad");
  }

  return (
    <div className="space-y-5 max-w-3xl">
      <PageHeader
        title="Single Call"
        subtitle="Place one outbound AI call. The agent answers when the callee picks up and uses the script below."
      />

      <Card>
        <div className="grid gap-6">

          {/* Row 1 — target */}
          <div className="grid md:grid-cols-2 gap-5">
            <Field label="Call to (E.164)">
              <Input
                placeholder="+9198XXXXXXXX"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />
            </Field>
            <Field label="Contact name (optional)">
              <Input
                placeholder="Ravi"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
          </div>

          {/* Row 2 — caller config */}
          <div className="grid md:grid-cols-2 gap-5">
            <Field
              label="Caller ID"
              hint={callerIds.length ? undefined : "Add an outbound number under Phone Numbers"}
            >
              <Select
                value={callerId}
                onChange={setCallerId}
                options={callerIds.length ? callerIds : [{ value: "", label: "— none —" }]}
              />
            </Field>
            <Field label="Language">
              <Select value={lang || "te"} onChange={setLang} options={LANGUAGES} />
            </Field>
          </div>

          {/* Row 3 — use case */}
          <Field label="Use-case">
            <Select value={useCaseType} onChange={setUseCaseType} options={USE_CASES} />
          </Field>

          {/* Row 4 — script */}
          <Field
            label="Call script / goal"
            hint="Overrides the global persona for this call only. Leave blank to use global."
          >
            <Textarea
              className="min-h-[120px]"
              placeholder="You are calling from Diigoo Consulting about their project enquiry. Speak in the caller's language. Ask what they want built, the rough timeline, and offer a free 20-minute consultation. 1–2 short sentences per turn, warm, never pushy."
              value={script}
              onChange={(e) => setScript(e.target.value)}
            />
          </Field>

          {/* Row 5 — voice */}
          <div className="grid md:grid-cols-2 gap-5">
            <Field label="Voice model (optional)">
              <Select
                value={voiceModel}
                onChange={(v) => { setVoiceModel(v); setVoiceSpeaker(""); }}
                options={[{ value: "", label: "Use global voice" }, ...TTS_MODELS]}
              />
            </Field>
            <Field label="Voice speaker (optional)">
              <Select
                value={voiceSpeaker}
                onChange={setVoiceSpeaker}
                options={
                  voiceModel
                    ? [{ value: "", label: "— pick —" }, ...speakersFor(voiceModel)]
                    : [{ value: "", label: "Use global voice" }]
                }
              />
            </Field>
          </div>

          {/* Advanced toggle */}
          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="text-[13px] text-[var(--muted)] hover:text-[var(--txt)] flex items-center gap-1.5 transition-colors"
            >
              <svg
                width="13" height="13" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
                style={{ transform: showAdvanced ? "rotate(90deg)" : "none", transition: "transform .15s" }}
              >
                <path d="M9 18l6-6-6-6" />
              </svg>
              Advanced overrides (per-call)
            </button>

            {showAdvanced && (
              <div className="grid gap-4 mt-4 pt-4 border-t border-[var(--line-soft)]">
                <Field label="Business description (this call)">
                  <Textarea
                    className="min-h-[80px]"
                    placeholder="Blank = global. Facts: services, hours, pricing/SMS policy."
                    value={businessDescription}
                    onChange={(e) => setBusinessDescription(e.target.value)}
                  />
                </Field>
                <Field label="Style example (this call)">
                  <Textarea
                    className="min-h-[80px]"
                    placeholder="Blank = neutral built-in. A short sample dialogue to steer tone/code-mix."
                    value={styleExamples}
                    onChange={(e) => setStyleExamples(e.target.value)}
                  />
                </Field>
                <Field label="Knowledge Base (this call)">
                  <Select
                    value={kbVectorStoreId}
                    onChange={setKbVectorStoreId}
                    options={kbOptions}
                  />
                </Field>
              </div>
            )}
          </div>

          {/* Action */}
          <div className="flex items-center gap-3 pt-1">
            <Button variant="primary" onClick={dial} disabled={busy}>
              {busy ? <Spinner /> : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.18 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13 1.05.36 2 .7 3a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.96.34 1.95.57 3 .7A2 2 0 0 1 22 16.92z" />
                </svg>
              )}
              Dial & talk to script
            </Button>
            {room && (
              <Link href={`/calls/${room}`} className="text-[var(--accent)] text-[13px] font-medium hover:underline">
                → Open live call
              </Link>
            )}
          </div>

        </div>
      </Card>
    </div>
  );
}
