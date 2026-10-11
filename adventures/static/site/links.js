document.querySelectorAll('a[href]').forEach((link) => {
  const url = new URL(link.href);
  const isWebLink = url.protocol === 'http:' || url.protocol === 'https:';
  const isContentLink = link.closest('.richtext-content');
  const isExternalLink = url.origin !== window.location.origin;

  if (isWebLink && (isContentLink || isExternalLink)) {
    link.target = '_blank';
    link.relList.add('noopener', 'noreferrer');
  }
});
