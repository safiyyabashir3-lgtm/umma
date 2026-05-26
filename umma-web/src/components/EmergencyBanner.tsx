import './EmergencyBanner.css';

interface Props {
  text: string;
}

export default function EmergencyBanner({ text }: Props) {
  return (
    <div className="emergency-banner">
      {text}
    </div>
  );
}
