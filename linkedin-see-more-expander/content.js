(() => {
  // Delay between individual button clicks (ms) — keeps LinkedIn's renderer happy
  const CLICK_DELAY_MS = 300;

  let totalClicked = 0;

  // ── helpers ────────────────────────────────────────────────────────────────────

  const getButtonText = (el) =>
    `${el.innerText || ""} ${el.getAttribute("aria-label") || ""}`
      .replace(/\s+/g, " ")
      .trim();

  const isSeeMoreButton = (el) =>
    /(^|[^\w])(?:…\s*)?(?:see )?more([^\w]|$)/i.test(getButtonText(el));

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const clickButton = async (btn) => {
    try {
      btn.click();
      totalClicked += 1;
      console.log(
        `[LinkedIn Expander] Clicked "${getButtonText(btn).slice(0, 40)}" · total: ${totalClicked}`
      );
      await sleep(CLICK_DELAY_MS);
    } catch {
      // LinkedIn may re-render the DOM mid-click — silently ignore
    }
  };

  // ── IntersectionObserver: click only when button enters the viewport ────────────

  // threshold:0 fires as soon as even 1px is visible
  const observer = new IntersectionObserver(
    async (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const btn = entry.target;
        observer.unobserve(btn); // fire once per button
        if (isSeeMoreButton(btn)) {
          await clickButton(btn);
        }
      }
    },
    { threshold: 0 }
  );

  // ── MutationObserver: watch for newly added buttons as LinkedIn lazy-loads posts

  const observeButtons = (root) => {
    root.querySelectorAll('button, [role="button"]').forEach((btn) => {
      if (isSeeMoreButton(btn)) {
        observer.observe(btn);
      }
    });
  };

  const mutationObserver = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType !== 1) continue; // elements only
        // The node itself might be a button
        if (
          (node.tagName === "BUTTON" || node.getAttribute?.("role") === "button") &&
          isSeeMoreButton(node)
        ) {
          observer.observe(node);
        }
        // Or it contains buttons (e.g. a whole new post card was inserted)
        observeButtons(node);
      }
    }
  });

  // ── start ──────────────────────────────────────────────────────────────────────

  console.log("[LinkedIn Expander] Active — watching for see-more buttons.");

  // Observe buttons already on the page at load time
  observeButtons(document.body);

  // Watch for new posts loaded as user scrolls
  mutationObserver.observe(document.body, { childList: true, subtree: true });
})();