// Знак «St»: буквы в квадрате, обозначенном двумя уголками — сверху слева и снизу справа

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg className="logo" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M1.5 11V1.5H11M30.5 21v9.5H21" />
      <text x="16" y="21.5">St</text>
    </svg>
  );
}
