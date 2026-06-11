import { Link } from 'react-router-dom';

import { Header } from '../components/ui/Header';

export function AboutPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="mx-auto max-w-2xl space-y-4 p-4 text-gray-700">
        <Link to="/" className="text-sm text-blue-600 hover:underline">
          ← Retour
        </Link>
        <h1 className="text-xl font-bold text-gray-800">À propos du projet</h1>
        <p>
          <strong>Surveillance Citoyenne de la Pollution à Dakar</strong> est un projet
          académique DIC2 (ESP Dakar, filière IABD) qui combine un réseau de capteurs IoT
          low-cost (ESP32, MQTT/LoRa), un pipeline de données temps réel
          (InfluxDB + PostgreSQL/PostGIS) et des modèles d'IA (calibration RandomForest,
          prédiction LSTM, détection d'anomalies IsolationForest, interpolation spatiale
          par Kriging).
        </p>
        <p>
          Les citoyens peuvent consulter l'indice de qualité de l'air (IQA) en temps réel,
          les prédictions à 1h/6h/24h, et signaler des épisodes de pollution. Les
          signalements sont analysés par NLP (spaCy) et corrélés aux anomalies détectées
          par les capteurs.
        </p>
        <p className="text-sm text-gray-500">
          Données simulées en Phase 3-4 (capteurs virtuels). © DIC2 ESP Dakar 2026 —
          équipe IABD/SSI/TR.
        </p>
      </main>
    </div>
  );
}
