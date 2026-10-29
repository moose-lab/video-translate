import { useEffect, useState } from "react";
import { api } from "../api/client";

type Language = {
  code: string;
  name: string;
  iso639_3: string | null;
  aliases: string[];
  direction: "ltr" | "rtl" | "auto";
  variants: string[];
  is_auto: boolean;
};
export default function LanguagePicker({
  target,
  value,
  onChange,
}: {
  target: boolean;
  value: string;
  onChange: (value: string) => void;
}) {
  const [query, setQuery] = useState(""),
    [items, setItems] = useState<Language[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({
      q: query,
      include_auto: String(!target),
      limit: "1000",
    });
    api<{ items: Language[] }>(`/languages?${params}`)
      .then((result) => {
        if (active) {
          setItems(result.items);
          setError("");
        }
      })
      .catch(() => {
        if (active) setError("语言目录加载失败");
      });
    return () => {
      active = false;
    };
  }, [query, target]);
  return (
    <div className="language-picker">
      <label>
        搜索语言
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          maxLength={100}
        />
      </label>
      {error && <p role="alert">{error}</p>}
      <p>
        已选择：<bdi>{value || "未选择"}</bdi>
      </p>
      <div className="language-results" role="group" aria-label="语言选项">
        {items.flatMap((item) =>
          [item.code, ...item.variants].map((tag) => (
            <button
              key={tag}
              type="button"
              className="secondary"
              onClick={() => onChange(tag)}
            >
              <bdi dir="auto">{item.name}</bdi> · {tag}
            </button>
          )),
        )}
      </div>
    </div>
  );
}
