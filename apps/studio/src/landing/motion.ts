import { animate, stagger } from 'animejs';

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

if (!reduced) {
  animate('.hero-copy > *', {
    opacity: [0, 1],
    translateY: [16, 0],
    duration: 760,
    delay: stagger(65),
    ease: 'outExpo',
  });

  animate('.visual-index, .visual-caption', {
    opacity: [0, 1],
    translateY: [10, 0],
    duration: 700,
    delay: stagger(90, { start: 520 }),
    ease: 'outExpo',
  });

  const stage = document.querySelector<HTMLElement>('.board-stage');
  const zone = document.querySelector<HTMLElement>('.hero-visual');

  if (stage) {
    animate(stage, {
      opacity: [0, 1],
      translateY: [30, 0],
      duration: 1200,
      ease: 'outExpo',
    });
  }

  if (stage && zone) {
    let frame = 0;
    let pending: { x: number; y: number } | null = null;

    const flush = (): void => {
      frame = 0;
      if (!pending) return;
      const { x, y } = pending;
      pending = null;
      animate(stage, { x, y, duration: 700, ease: 'outExpo' });
    };

    zone.addEventListener('pointermove', (event) => {
      const rect = zone.getBoundingClientRect();
      const nx = (event.clientX - rect.left) / rect.width - 0.5;
      const ny = (event.clientY - rect.top) / rect.height - 0.5;
      pending = { x: nx * 8, y: ny * 6 };
      if (!frame) frame = requestAnimationFrame(flush);
    });

    zone.addEventListener('pointerleave', () => {
      pending = { x: 0, y: 0 };
      if (!frame) frame = requestAnimationFrame(flush);
    });
  }
}
