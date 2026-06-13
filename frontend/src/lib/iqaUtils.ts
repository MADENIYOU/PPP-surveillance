// Utilitaires IQA — même grille que le backend (iqa_calculator.py)

export function getIQAColor(iqa: number | null): string {
  if (iqa == null) return '#9CA3AF';
  if (iqa <= 50) return '#00E400';
  if (iqa <= 100) return '#FFA500';
  if (iqa <= 150) return '#FF7E00';
  if (iqa <= 200) return '#FF0000';
  if (iqa <= 300) return '#8F3F97';
  return '#7E0023';
}

export function getIQALabel(iqa: number | null): string {
  if (iqa == null) return 'Indisponible';
  if (iqa <= 50) return 'Bon';
  if (iqa <= 100) return 'Modéré';
  if (iqa <= 150) return 'Mauvais (sensibles)';
  if (iqa <= 200) return 'Mauvais';
  if (iqa <= 300) return 'Très mauvais';
  return 'Dangereux';
}

export function pm25ToHexColor(pm25: number): string {
  if (pm25 <= 25) return '#00E400';
  if (pm25 <= 55) return '#FFFF00';
  if (pm25 <= 150) return '#FF7E00';
  if (pm25 <= 250) return '#FF0000';
  if (pm25 <= 350) return '#8F3F97';
  return '#7E0023';
}

export function getHealthAdvice(iqa: number): string {
  if (iqa <= 50) return "La qualité de l'air est bonne. Profitez de vos activités extérieures sans restriction.";
  if (iqa <= 100) return "Qualité de l'air acceptable. Les personnes très sensibles (asthme sévère) peuvent ressentir une gêne légère.";
  if (iqa <= 150) return "Les enfants, asthmatiques et personnes âgées doivent réduire les efforts prolongés en extérieur. Port du masque recommandé.";
  if (iqa <= 200) return "Tout le monde peut ressentir des effets. Port du masque fortement recommandé. Évitez les activités physiques intenses.";
  if (iqa <= 300) return "Alerte sanitaire. Limitez les déplacements. Fermez les fenêtres. Contactez un médecin si symptômes respiratoires.";
  return "Urgence sanitaire. Restez à l'intérieur. Masque obligatoire. Suivez les consignes des autorités.";
}

export function getAQIColor(value: number, pollutant: string): string {
  if (pollutant === "pm25") {
    if (value <= 25) return "#00E400";
    if (value <= 50) return "#FFFF00";
    if (value <= 100) return "#FF7E00";
    if (value <= 180) return "#FF0000";
    if (value <= 350) return "#8F3F97";
    return "#7E0023";
  }
  const iqa = Math.min(500, (value / (pollutant === "pm10" ? 425 : 100)) * 150);
  return getIQAColor(iqa);
}

export function getUnit(pollutant: string): string {
  switch (pollutant) {
    case 'pm25':
    case 'pm10':
      return 'µg/m³';
    case 'no2':
      return 'ppb';
    case 'co':
      return 'ppm';
    case 'temperature':
      return '°C';
    case 'humidity':
      return '%';
    default:
      return '';
  }
}
