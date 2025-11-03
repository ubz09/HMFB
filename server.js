// server.js
import express from "express";
import fetch from "node-fetch";
import dotenv from "dotenv";
import { Client, GatewayIntentBits } from "discord.js";
import path from "path";
import { fileURLToPath } from "url";

dotenv.config();
const app = express();
app.use(express.json());

// --- Discord Bot Config ---
const client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMembers] });
client.login(process.env.BOT_TOKEN);

// --- Paths ---
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
app.use(express.static(__dirname));

// --- Discord OAuth URLs ---
const CLIENT_ID = process.env.CLIENT_ID;
const CLIENT_SECRET = process.env.CLIENT_SECRET;
const REDIRECT_URI = "https://hmfb-production.up.railway.app/auth/discord/callback"; // ⚠️ cambia si tu dominio es distinto

// Ruta para redirigir al login de Discord
app.get("/auth/discord", (req, res) => {
  const redirect = `https://discord.com/api/oauth2/authorize?client_id=${CLIENT_ID}&redirect_uri=${encodeURIComponent(
    REDIRECT_URI
  )}&response_type=code&scope=identify`;
  res.redirect(redirect);
});

// Callback de Discord (devuelve info del usuario)
app.get("/auth/discord/callback", async (req, res) => {
  const code = req.query.code;
  if (!code) return res.status(400).json({ error: "Falta el parámetro 'code'" });

  try {
    // 1️⃣ Intercambiar el code por un token
    const tokenRes = await fetch("https://discord.com/api/oauth2/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: CLIENT_ID,
        client_secret: CLIENT_SECRET,
        grant_type: "authorization_code",
        code,
        redirect_uri: REDIRECT_URI,
      }),
    });

    const tokenData = await tokenRes.json();
    if (!tokenData.access_token) return res.status(400).json({ error: "No se pudo obtener el token." });

    // 2️⃣ Obtener datos del usuario
    const userRes = await fetch("https://discord.com/api/users/@me", {
      headers: { Authorization: `Bearer ${tokenData.access_token}` },
    });

    const user = await userRes.json();
    res.json(user);
  } catch (err) {
    console.error("Error OAuth2:", err);
    res.status(500).json({ error: "Error en autenticación" });
  }
});

// --- Endpoint para asignar rol ---
app.post("/assign-role", async (req, res) => {
  const { discordId, paquete } = req.body;
  const guildId = process.env.GUILD_ID;

  const roles = {
    "1mes": process.env.ROLE_1MES,
    "3meses": process.env.ROLE_3MESES,
    "6meses": process.env.ROLE_6MESES,
    "permanente": process.env.ROLE_PERMANENTE,
  };
  const roleId = roles[paquete];
  if (!discordId || !roleId) return res.json({ ok: false, error: "Datos inválidos" });

  try {
    const guild = await client.guilds.fetch(guildId);
    const member = await guild.members.fetch(discordId);
    await member.roles.add(roleId);
    console.log(`✅ Rol ${paquete} asignado a ${discordId}`);
    res.json({ ok: true });
  } catch (err) {
    console.error("Error asignando rol:", err);
    res.json({ ok: false, error: err.message });
  }
});

// --- Inicio del servidor ---
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`🚀 Servidor corriendo en puerto ${PORT}`));
