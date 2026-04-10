export default function SectionTitle({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="mb-4">
      <div className="text-lg font-semibold tracking-tight text-white">{title}</div>
      {subtitle ? <div className="mt-1 text-sm text-white/45">{subtitle}</div> : null}
    </div>
  );
}
