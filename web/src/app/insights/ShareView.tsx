/**
 * The share view (ADR-116): one story's card at landscape 1200×675 or portrait 1080×1350, in a
 * focused dialog. The preview is the card itself — the SVG the PNG is made from, with the
 * self-hosted faces embedded — scaled down to fit the screen, so the download is exactly what
 * the reader looked at. Loaded only when a reader opens it.
 */

import { useEffect, useMemo, useState } from "react";

import { Modal } from "../../components/Modal";
import { Segmented } from "../../components/primitives";
import { exportFilename, type InsightStory } from "../../data/insights";
import { copyText } from "./copy";
import { downloadBlob, embeddedFontCss, loadFaces, logoDataUrl, rasterize, svgDataUrl } from "./exportPng";
import { canvasMeasure, type TextStyle } from "./marks";
import { SHARE_SIZES, buildShareCard, type ShareCard, type ShareInput, type ShareLayoutId } from "./shareCard";

/** Every face and weight a card draws with, loaded before a line is measured. */
const FACES: readonly TextStyle[] = [
  { size: 16, weight: 400, face: "sans" },
  { size: 16, weight: 500, face: "sans" },
  { size: 16, weight: 600, face: "sans" },
  { size: 16, weight: 700, face: "sans" },
  { size: 16, weight: 500, face: "mono" },
  { size: 16, weight: 600, face: "mono" },
  { size: 16, weight: 700, face: "mono" },
];

const LAYOUT_NAMES: Readonly<Record<ShareLayoutId, string>> = {
  land: "Landscape",
  port: "Portrait",
};

export interface ShareViewProps {
  readonly story: InsightStory;
  readonly layout: ShareLayoutId;
  readonly input: Omit<ShareInput, "story" | "layout" | "measure">;
  readonly link: string;
  readonly summary: string;
  readonly onLayout: (layout: ShareLayoutId) => void;
  readonly onClose: () => void;
}

interface Prepared {
  readonly key: string;
  readonly card: ShareCard;
  readonly svg: string;
}

function sampleText(story: InsightStory, input: ShareViewProps["input"]): string {
  return [
    story.headline,
    story.dek,
    story.display_name,
    story.caveat,
    story.counterpoint ?? "",
    ...story.facts.flatMap((fact) => [fact.label, fact.value]),
    ...input.context,
    input.edition,
    input.window,
    input.scoring,
    ...input.sources,
    input.withdrawn ?? "",
    "0123456789%·–—×#≤ JEISEY TIERS",
  ].join(" ");
}

export function ShareView({ story, layout, input, link, summary, onLayout, onClose }: ShareViewProps): React.JSX.Element {
  const key = `${story.story_id}|${layout}|${input.withdrawn ?? ""}`;
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [message, setMessage] = useState<{ readonly ok: boolean; readonly text: string } | null>(null);
  const [fallback, setFallback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const size = SHARE_SIZES[layout];

  useEffect(() => {
    let live = true;
    void (async () => {
      await loadFaces(FACES, sampleText(story, input));
      const card = buildShareCard({ ...input, story, layout, measure: canvasMeasure() });
      const [fontCss, logo] = await Promise.all([
        embeddedFontCss(card.texts.map((text) => text.text).join("")),
        logoDataUrl(),
      ]);
      if (live) setPrepared({ key, card, svg: card.toSvg(fontCss, logo) });
    })().catch((error: unknown) => {
      if (live) setFailed(error instanceof Error ? error.message : String(error));
    });
    return () => {
      live = false;
    };
    // `key` names everything the card is drawn from.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const current = prepared?.key === key ? prepared : null;
  const overflow = useMemo(
    () => (current === null ? null : current.card.texts.filter((text) => text.width > text.maxWidth + 0.5).length),
    [current],
  );

  const download = (): void => {
    if (current === null) return;
    setBusy(true);
    rasterize(current.svg, size.width, size.height)
      .then((blob) => {
        downloadBlob(blob, exportFilename(story, layout));
        setMessage({ ok: true, text: `Downloaded ${exportFilename(story, layout)} (${String(size.width)} × ${String(size.height)} px).` });
      })
      .catch((error: unknown) => {
        setMessage({ ok: false, text: `The PNG could not be made: ${error instanceof Error ? error.message : String(error)}.` });
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const copy = (what: "link" | "summary"): void => {
    const text = what === "link" ? link : summary;
    void copyText(text).then((ok) => {
      setMessage({ ok, text: ok ? (what === "link" ? "Link copied." : "Summary copied.") : `Could not copy the ${what}. Select it below and copy it.` });
      setFallback(ok ? null : text);
    });
  };

  return (
    <Modal title="Share this story" onClose={onClose} wide>
      <div className="ins-share" data-layout={layout}>
        <div className="ins-share-controls">
          <Segmented<ShareLayoutId>
            name="share-layout"
            label="Layout"
            value={layout}
            options={[
              { value: "land", label: "Landscape", description: "Landscape, 1200 by 675 pixels" },
              { value: "port", label: "Portrait", description: "Portrait, 1080 by 1350 pixels" },
            ]}
            onChange={onLayout}
          />
          <p className="ins-share-note">
            {`${LAYOUT_NAMES[layout]} ${String(size.width)} × ${String(size.height)} px. The preview is the image that downloads, scaled to fit.`}
          </p>
        </div>
        <div
          className="ins-share-preview"
          data-ready={current !== null || undefined}
          data-fits={current === null ? undefined : String(current.card.fits)}
          data-scale={current === null ? undefined : String(current.card.scale)}
          data-overflow={overflow === null ? undefined : String(overflow)}
          style={{ aspectRatio: `${String(size.width)} / ${String(size.height)}` }}
        >
          {current !== null ? (
            <img
              src={svgDataUrl(current.svg)}
              width={size.width}
              height={size.height}
              alt={`Share card (${LAYOUT_NAMES[layout].toLowerCase()}): ${story.headline} ${story.display_name}. Caveat: ${story.caveat}`}
            />
          ) : (
            <p className="ins-share-wait" role="status">
              {failed === null ? "Preparing the card…" : `The card could not be prepared: ${failed}`}
            </p>
          )}
        </div>
        <div className="ins-actions">
          <button type="button" className="button" data-variant="primary" disabled={current === null || busy} onClick={download}>
            Download PNG
          </button>
          <button
            type="button"
            className="button"
            onClick={() => {
              copy("link");
            }}
          >
            Copy link
          </button>
          <button
            type="button"
            className="button"
            onClick={() => {
              copy("summary");
            }}
          >
            Copy summary
          </button>
        </div>
        <p className="ins-copy-status" role="status" aria-live="polite" data-ok={message === null ? undefined : String(message.ok)}>
          {message?.text ?? ""}
        </p>
        {fallback !== null && (
          <label className="ins-copy-fallback">
            <span className="visually-hidden">Text to copy</span>
            <textarea
              readOnly
              rows={fallback === link ? 2 : 8}
              value={fallback}
              onFocus={(event) => {
                event.currentTarget.select();
              }}
            />
          </label>
        )}
        <p className="ins-share-link">
          <span className="control-label">Link</span> <code>{link}</code>
        </p>
      </div>
    </Modal>
  );
}
