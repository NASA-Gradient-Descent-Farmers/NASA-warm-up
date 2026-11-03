import { initializeApp } from "firebase/app";
import { initializeAppCheck, ReCaptchaEnterpriseProvider } from "firebase/app-check";
import { getAI, getGenerativeModel, GoogleAIBackend, Schema } from "firebase/ai";
import type { Card } from "../types";
import { explainerPayload, explainerPrompt, fallbackExplanation, SYSTEM_INSTRUCTION, ungroundedNumbers, type Explanation } from "./explain";

const env = import.meta.env;
const MODEL = env.VITE_GEMINI_MODEL ?? "gemini-3.8-flash";

const config = {
  apiKey: env.VITE_FIREBASE_API_KEY, authDomain: env.VITE_FIREBASE_AUTH_DOMAIN, projectId: env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: env.VITE_FIREBASE_STORAGE_BUCKET, messagingSenderId: env.VITE_FIREBASE_MESSAGING_SENDER_ID, appId: env.VITE_FIREBASE_APP_ID,
};

export const geminiConfigured = Boolean(config.apiKey && config.projectId && config.appId);

let model: ReturnType<typeof getGenerativeModel> | null = null;

function getModel() {
  if (model) return model;
  const app = initializeApp(config);
  // App Check protects the Firebase AI Logic quota. Debug token for local development (register it in the console).
  if (env.DEV) (self as unknown as { FIREBASE_APPCHECK_DEBUG_TOKEN?: boolean }).FIREBASE_APPCHECK_DEBUG_TOKEN = true;
  if (env.VITE_APPCHECK_SITE_KEY) {
    initializeAppCheck(app, { provider: new ReCaptchaEnterpriseProvider(env.VITE_APPCHECK_SITE_KEY), isTokenAutoRefreshEnabled: true });
  }
  const ai = getAI(app, { backend: new GoogleAIBackend() });
  const list = Schema.array({ items: Schema.string() });
  model = getGenerativeModel(ai, {
    model: MODEL,
    systemInstruction: SYSTEM_INSTRUCTION,
    generationConfig: {
      responseMimeType: "application/json",
      temperature: 0.3,
      responseSchema: Schema.object({
        properties: {
          summary: Schema.string(), whyThisRotation: Schema.string(), tradeoffs: list, risks: list,
          whatToCheckLocally: list, recommendation: Schema.string(),
        },
      }),
    },
  });
  return model;
}

export interface ExplainResult { explanation: Explanation; source: "gemini" | "fallback"; warning?: string }

export async function explainCard(card: Card, cropNames: Record<string, string>, scenario: { rainPct: number; tempC: number }, language: string): Promise<ExplainResult> {
  const fallback = fallbackExplanation(card, cropNames);
  if (!geminiConfigured) return { explanation: fallback, source: "fallback", warning: "Gemini is not configured (missing VITE_FIREBASE_* settings). Showing the built-in explanation." };
  const payload = explainerPayload(card, cropNames, scenario);
  try {
    const result = await getModel().generateContent(explainerPrompt(payload, language));
    const explanation = JSON.parse(result.response.text()) as Explanation;
    const bad = ungroundedNumbers(explanation, payload);
    if (bad.length) return { explanation: fallback, source: "fallback", warning: `The AI answer used numbers not found in the data (${bad.join(", ")}), so it was discarded.` };
    return { explanation, source: "gemini" };
  } catch (error) {
    return { explanation: fallback, source: "fallback", warning: `Gemini request failed: ${error instanceof Error ? error.message : String(error)}` };
  }
}

