function enableHomepageCodeKeyboardScrolling() {
  if (!document.querySelector('.framework-hero')) return;
  document.querySelectorAll('main .sl-markdown-content pre').forEach((pre) => {
    if (pre.scrollWidth > pre.clientWidth) pre.tabIndex = 0;
  });
}

enableHomepageCodeKeyboardScrolling();
document.addEventListener('astro:page-load', enableHomepageCodeKeyboardScrolling);
window.addEventListener('resize', enableHomepageCodeKeyboardScrolling);
