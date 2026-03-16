function normalizeHandleFromUrl(url) {
  if (!url) return null;
  try {
    const parsed = new URL(url, window.location.origin);
    const segments = parsed.pathname.split("/").filter(Boolean);
    if (!segments.length) return null;
    const first = segments[0];
    if (first === "profile.php") {
      return parsed.searchParams.get("id") || null;
    }
    const reserved = new Set([
      "photo",
      "photos",
      "posts",
      "permalink.php",
      "story.php",
      "watch",
      "reel",
      "reels",
      "groups",
      "events",
      "marketplace",
      "hashtag",
      "share",
      "plugins",
      "login",
      "help",
      "messages"
    ]);
    if (reserved.has(first.toLowerCase())) {
      return null;
    }
    return first;
  } catch {
    return null;
  }
}

function normalizeAccountId(handle, href, fallbackSeed) {
  if (handle) return `handle:${handle.toLowerCase()}`;
  const byUrl = normalizeHandleFromUrl(href);
  if (byUrl) return `handle:${byUrl.toLowerCase()}`;
  return `anon:${fallbackSeed}`;
}

function textFrom(el) {
  return (el?.textContent || "").replace(/\s+/g, " ").trim();
}

function collectMentions(text) {
  if (!text) return [];
  const matches = [...text.matchAll(/@([A-Za-z0-9_.]{2,30})/g)];
  return [...new Set(matches.map((m) => m[1].toLowerCase()))];
}

async function oneExpansionPass() {
  const candidates = Array.from(document.querySelectorAll("div[role='button'], span[role='button']"));
  const buttons = candidates.filter((el) => {
    const t = textFrom(el).toLowerCase();
    return (
      t.includes("view more replies") ||
      t.includes("view more comments") ||
      t.includes("see more")
    );
  });

  for (const button of buttons.slice(0, 20)) {
    try {
      button.click();
      await new Promise((resolve) => setTimeout(resolve, 175));
    } catch {}
  }
}

function findPageOwner() {
  const ownerName = textFrom(document.querySelector("h1")) || "facebook-page";

  const candidateUrls = [];
  const canonical = document.querySelector("link[rel='canonical']")?.getAttribute("href");
  const ogUrl = document.querySelector("meta[property='og:url']")?.getAttribute("content");
  if (canonical) candidateUrls.push(canonical);
  if (ogUrl) candidateUrls.push(ogUrl);
  candidateUrls.push(window.location.href);

  let href = "";
  let handle = null;
  for (const candidate of candidateUrls) {
    const maybe = normalizeHandleFromUrl(candidate);
    if (maybe) {
      href = candidate;
      handle = maybe;
      break;
    }
  }

  if (!handle) {
    const profileAnchors = Array.from(
      document.querySelectorAll(
        "h1 a[href*='facebook.com/'], h2 a[href*='facebook.com/'], a[href*='facebook.com/'][role='link']"
      )
    );
    for (const anchor of profileAnchors) {
      const candidateHref = anchor.getAttribute("href") || "";
      const maybe = normalizeHandleFromUrl(candidateHref);
      if (maybe) {
        href = candidateHref;
        handle = maybe;
        break;
      }
    }
  }

  if (!href) {
    href = window.location.href;
  }

  return {
    platform_account_id: normalizeAccountId(handle, href, "page-owner"),
    handle,
    display_name: ownerName,
    profile_url: href
  };
}

function readCommentBlocks() {
  const selectors = [
    "div[aria-label*='Comment']",
    "div[role='article']",
    "div[data-ad-preview='message']"
  ];
  const seen = new Set();
  const blocks = [];
  for (const selector of selectors) {
    for (const el of document.querySelectorAll(selector)) {
      if (seen.has(el)) continue;
      seen.add(el);
      blocks.push(el);
    }
  }
  return blocks;
}

function extractAuthor(block, index) {
  const links = Array.from(block.querySelectorAll("a[href*='facebook.com']"));
  let chosenLink = null;
  let handle = null;
  for (const link of links) {
    const href = link.getAttribute("href") || "";
    const maybe = normalizeHandleFromUrl(href);
    if (maybe) {
      chosenLink = link;
      handle = maybe;
      break;
    }
  }

  if (!chosenLink && links.length) {
    chosenLink = links[0];
  }

  const displayName = textFrom(chosenLink) || textFrom(block.querySelector("strong")) || `User ${index}`;
  const href = chosenLink?.getAttribute("href") || "";
  if (!handle) {
    handle = normalizeHandleFromUrl(href);
  }
  return {
    platform_account_id: normalizeAccountId(handle, href, `commenter-${index}`),
    handle,
    display_name: displayName,
    profile_url: href || null
  };
}

function extractCommentText(block) {
  const textEl =
    block.querySelector("div[dir='auto']") ||
    block.querySelector("span[dir='auto']") ||
    block;
  return textFrom(textEl).slice(0, 4000);
}

function extractContentRef(block, index) {
  const idAttr = block.getAttribute("id") || block.dataset?.commentid || null;
  const link = block.querySelector("a[href*='comment_id='], a[href*='/posts/'], a[href*='/permalink/']");
  const href = link?.getAttribute("href") || window.location.href;
  const contentId = idAttr || (link ? link.href : `visible-${index}`);
  return {
    content_id: contentId,
    content_url: href,
    parent_content_id: null,
    evidence_ref: href
  };
}

function buildInteractions() {
  const owner = findPageOwner();
  const blocks = readCommentBlocks();
  const interactions = [];

  blocks.forEach((block, idx) => {
    const source = extractAuthor(block, idx);
    const text = extractCommentText(block);
    if (!text) return;

    const ref = extractContentRef(block, idx);

    interactions.push({
      interaction_type: "comment",
      source_account: source,
      target_account: owner,
      content_id: ref.content_id,
      content_url: ref.content_url,
      parent_content_id: ref.parent_content_id,
      text_snippet: text,
      evidence_ref: ref.evidence_ref,
      occurred_at: new Date().toISOString()
    });

    const mentions = collectMentions(text);
    if (mentions.length) {
      const replyTarget = mentions[0];
      interactions.push({
        interaction_type: "reply",
        source_account: source,
        target_account: {
          platform_account_id: `handle:${replyTarget}`,
          handle: replyTarget,
          display_name: replyTarget,
          profile_url: null
        },
        content_id: ref.content_id,
        content_url: ref.content_url,
        parent_content_id: ref.parent_content_id,
        text_snippet: text,
        evidence_ref: ref.evidence_ref,
        occurred_at: new Date().toISOString()
      });

      for (const mentioned of mentions) {
        interactions.push({
          interaction_type: "mention",
          source_account: source,
          target_account: {
            platform_account_id: `handle:${mentioned}`,
            handle: mentioned,
            display_name: mentioned,
            profile_url: null
          },
          content_id: ref.content_id,
          content_url: ref.content_url,
          parent_content_id: ref.parent_content_id,
          text_snippet: text,
          evidence_ref: ref.evidence_ref,
          occurred_at: new Date().toISOString()
        });
      }
    }
  });

  return interactions;
}

async function buildCapturePayload() {
  await oneExpansionPass();
  return {
    platform: "facebook",
    captured_at: new Date().toISOString(),
    page_url: window.location.href,
    collector_version: "firefox-facebook-v1",
    interactions: buildInteractions()
  };
}

window.__facefieldCollectSocial = buildCapturePayload;

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "CAPTURE_SOCIAL_PING") {
    sendResponse({ ok: true });
    return false;
  }

  if (message?.type !== "CAPTURE_SOCIAL") {
    return false;
  }

  buildCapturePayload()
    .then((payload) => {
      sendResponse({ ok: true, payload });
    })
    .catch((error) => {
      sendResponse({ ok: false, error: String(error) });
    });

  return true;
});
