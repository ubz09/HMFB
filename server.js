import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import fetch from "node-fetch";
import { Client, GatewayIntentBits } from "discord.js";

dotenv.config();

const app = express();
app.use(cors());
app.use(express.json());

// --- Configuración del bot de Discord ---
const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMembers],
});

const DISCORD_TOKEN = process.env.DISCORD_BOT_TOKEN;
const GUILD_ID = process.env.DISCORD_GUILD_ID;

client.once("ready", () => {
  console.log(`🤖 Bot conectado como ${client.user.tag}`);
});

client.login(DISCORD_TOKEN);

// --- Endpoint para asignar roles ---
app.post("/asignar-rol", async (req, res) => {
  try {
    const { discordId, paquete } = req.body;
    const guild = await client.guilds.fetch(GUILD_ID);
    const member = await guild.members.fetch(discordId);

    // Roles según el paquete
    const roles = {
      basico: process.env.ROL_BASICO_ID,
      premium: process.env.ROL_PREMIUM_ID,
      elite: process.env.ROL_ELITE_ID,
    };

    const roleId = roles[paquete];
    if (!roleId) throw new Error("Paquete no válido");

    await member.roles.add(roleId);
    console.log(`✅ Rol ${paquete} asignado a ${discordId}`);
    res.json({ ok: true });
  } catch (err) {
    console.error("❌ Error asignando rol:", err);
    res.json({ ok: false, error: err.message });
  }
});

// --- Iniciar servidor web ---
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`🚀 Servidor corriendo en puerto ${PORT}`));
