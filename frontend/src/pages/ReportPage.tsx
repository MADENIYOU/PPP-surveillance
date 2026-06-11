import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { MapContainer, Marker, TileLayer, useMapEvents } from 'react-leaflet';
import { Link, useNavigate } from 'react-router-dom';
import { z } from 'zod';

import { Header } from '../components/ui/Header';
import { ApiError, apiPost, getToken, setToken } from '../lib/apiClient';
import type { ReportCreate, TokenResponse } from '../types/api';

const reportSchema = z.object({
  description: z
    .string()
    .min(10, 'Description trop courte (min 10 caractères)')
    .max(500, 'Description trop longue (max 500 caractères)'),
  lat: z.number().min(14.5).max(14.9),
  lon: z.number().min(-17.6).max(-17.2),
  type: z.enum(['smoke', 'dust', 'odor', 'chemical', 'noise', 'other']),
  intensity: z.enum(['low', 'medium', 'high']),
});

const TYPES = [
  { value: 'smoke', label: 'Fumée' },
  { value: 'dust', label: 'Poussière' },
  { value: 'odor', label: 'Odeur' },
  { value: 'chemical', label: 'Produit chimique' },
  { value: 'noise', label: 'Bruit' },
  { value: 'other', label: 'Autre' },
] as const;

const INTENSITIES = [
  { value: 'low', label: 'Légère' },
  { value: 'medium', label: 'Modérée' },
  { value: 'high', label: 'Forte' },
] as const;

function LocationPicker({
  position,
  onPick,
}: {
  position: { lat: number; lon: number } | null;
  onPick: (lat: number, lon: number) => void;
}) {
  function ClickHandler() {
    useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) });
    return null;
  }
  return (
    <MapContainer center={[14.7167, -17.4677]} zoom={12} style={{ height: 240 }}>
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <ClickHandler />
      {position && <Marker position={[position.lat, position.lon]} />}
    </MapContainer>
  );
}

export function ReportPage() {
  const navigate = useNavigate();
  const [description, setDescription] = useState('');
  const [type, setType] = useState<ReportCreate['type']>('smoke');
  const [intensity, setIntensity] = useState<ReportCreate['intensity']>('medium');
  const [position, setPosition] = useState<{ lat: number; lon: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const login = useMutation({
    mutationFn: () => apiPost<TokenResponse>('/auth/login', { email, password }),
    onSuccess: (data) => {
      setToken(data.access_token);
      setError(null);
    },
    onError: () => setError('Email ou mot de passe incorrect.'),
  });

  const submitReport = useMutation({
    mutationFn: (data: ReportCreate) => apiPost('/reports', data),
    onSuccess: () => navigate('/'),
    onError: (err: Error) => {
      if (err instanceof ApiError && err.status === 429) {
        setError('Trop de signalements. Attendez quelques minutes.');
      } else if (err instanceof ApiError && err.status === 401) {
        setToken(null);
        setError('Session expirée — reconnectez-vous.');
      } else {
        setError(err.message || "Erreur lors de l'envoi");
      }
    },
  });

  const handleGetLocation = () => {
    if (!navigator.geolocation) {
      setError('Géolocalisation non supportée par votre navigateur');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => setPosition({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => setError("Impossible d'obtenir votre position"),
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!position) {
      setError('Choisissez une position (carte ou GPS).');
      return;
    }
    const parsed = reportSchema.safeParse({ description, ...position, type, intensity });
    if (!parsed.success) {
      setError(parsed.error.errors[0]?.message ?? 'Formulaire invalide');
      return;
    }
    submitReport.mutate(parsed.data);
  };

  const authenticated = !!getToken();

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="mx-auto max-w-xl space-y-4 p-4">
        <Link to="/" className="text-sm text-blue-600 hover:underline">
          ← Retour
        </Link>
        <h1 className="text-xl font-bold text-gray-800">Signaler une pollution</h1>

        {!authenticated && (
          <form
            className="space-y-2 rounded-lg border border-gray-200 bg-white p-4"
            onSubmit={(e) => {
              e.preventDefault();
              login.mutate();
            }}
          >
            <p className="text-sm text-gray-600">Connectez-vous pour signaler :</p>
            <input
              type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="Email" aria-label="Email"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
            <input
              type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder="Mot de passe" aria-label="Mot de passe"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
            <button type="submit" disabled={login.isPending}
                    className="rounded bg-slate-800 px-4 py-2 text-sm font-medium text-white">
              Se connecter
            </button>
          </form>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border border-gray-200 bg-white p-4">
          <div>
            <label htmlFor="description" className="block text-sm font-medium text-gray-700">
              Description *
            </label>
            <textarea
              id="description" rows={3} value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Décrivez ce que vous observez (min. 10 caractères)…"
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
            <span className="text-xs text-gray-400">{description.length}/500 caractères</span>
          </div>

          <fieldset>
            <legend className="text-sm font-medium text-gray-700">Type de pollution observée</legend>
            <div className="mt-1 flex flex-wrap gap-1">
              {TYPES.map((t) => (
                <button key={t.value} type="button" onClick={() => setType(t.value)}
                        aria-pressed={type === t.value}
                        className={`rounded px-3 py-1 text-sm ${
                          type === t.value ? 'bg-slate-800 text-white' : 'bg-gray-100 hover:bg-gray-200'
                        }`}>
                  {t.label}
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend className="text-sm font-medium text-gray-700">Intensité</legend>
            <div className="mt-1 flex gap-1">
              {INTENSITIES.map((i) => (
                <button key={i.value} type="button" onClick={() => setIntensity(i.value)}
                        aria-pressed={intensity === i.value}
                        className={`rounded px-3 py-1 text-sm ${
                          intensity === i.value ? 'bg-blue-600 text-white' : 'bg-gray-100 hover:bg-gray-200'
                        }`}>
                  {i.label}
                </button>
              ))}
            </div>
          </fieldset>

          <div>
            <span className="text-sm font-medium text-gray-700">Localisation</span>
            <div className="mt-1 overflow-hidden rounded border border-gray-300">
              <LocationPicker position={position} onPick={(lat, lon) => setPosition({ lat, lon })} />
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-gray-600">
              <button type="button" onClick={handleGetLocation} className="text-blue-600 hover:underline">
                📍 Utiliser ma position GPS
              </button>
              {position && (
                <span>
                  Position : {position.lat.toFixed(4)}°N, {Math.abs(position.lon).toFixed(4)}°W ✓
                </span>
              )}
            </div>
          </div>

          {error && <p className="rounded bg-red-50 p-2 text-sm text-red-700">{error}</p>}

          <button type="submit" disabled={submitReport.isPending || !authenticated}
                  className="w-full rounded bg-orange-500 px-4 py-2 font-medium text-white hover:bg-orange-600 disabled:opacity-50">
            {submitReport.isPending ? 'Envoi…' : 'Envoyer le signalement'}
          </button>
          <p className="text-xs text-gray-500">
            ℹ️ Votre position exacte ne sera pas divulguée publiquement.
          </p>
        </form>
      </main>
    </div>
  );
}
