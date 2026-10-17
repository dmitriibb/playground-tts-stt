import type { TtsMode } from "../../api/types";
import { createRowsStore } from "../stt/store";

export interface TtsRowConfig {
  id: string;
  modelId: string;
  voice: string;
  language: string;
  speed: number;
  mode: TtsMode;
  text: string;
}

let counter = 0;
export const newTtsRowId = () => `tts-${Date.now().toString(36)}-${counter++}`;

export const PRESETS: Record<string, Record<"short" | "medium" | "long", string>> = {
  en: {
    short: "Hello! This is a quick test of speech synthesis.",
    medium:
      "Speech synthesis turns written text into audio. Streaming lets the listener hear the first words " +
      "before the whole answer is ready, which makes a voice assistant feel much faster.",
    long:
      "Yesterday we compared several voices on the same machine. The first one started speaking almost " +
      "immediately, but its intonation sounded a little flat. The second one took longer to begin, yet it " +
      "read numbers like 1,250 and dates like March 3rd naturally. In the afternoon we ran ten clients at " +
      "once to see how the queue grows, and how long each of them waited for the first audio chunk.",
  },
  ru: {
    short: "Привет! Это быстрая проверка синтеза речи.",
    medium:
      "Синтез речи превращает текст в звук. Потоковая передача позволяет услышать первые слова до того, " +
      "как весь ответ будет готов, и голосовой помощник кажется намного быстрее.",
    long:
      "Вчера мы сравнили несколько голосов на одном компьютере. Первый начал говорить почти сразу, но его " +
      "интонация звучала немного плоско. Второму понадобилось больше времени, зато он естественно читал " +
      "числа и даты. После обеда мы запустили десять клиентов одновременно, чтобы увидеть, как растёт " +
      "очередь и сколько каждый из них ждёт первого фрагмента звука.",
  },
  de: {
    short: "Hallo! Das ist ein kurzer Test der Sprachsynthese.",
    medium:
      "Sprachsynthese verwandelt geschriebenen Text in Audio. Beim Streaming hört man die ersten Wörter, " +
      "bevor die ganze Antwort fertig ist, und ein Sprachassistent wirkt viel schneller.",
    long:
      "Gestern haben wir mehrere Stimmen auf demselben Rechner verglichen. Die erste begann fast sofort zu " +
      "sprechen, klang aber etwas monoton. Die zweite brauchte länger, las jedoch Zahlen und Daten ganz " +
      "natürlich vor. Am Nachmittag haben wir zehn Clients gleichzeitig gestartet, um zu sehen, wie die " +
      "Warteschlange wächst und wie lange jeder auf das erste Audiostück wartet.",
  },
};

export const defaultTtsRow = (): TtsRowConfig => ({
  id: newTtsRowId(),
  modelId: "",
  voice: "",
  language: "en",
  speed: 1,
  mode: "tts_stream",
  text: PRESETS.en.medium,
});

export const useTtsRows = createRowsStore<TtsRowConfig>([defaultTtsRow()]);
