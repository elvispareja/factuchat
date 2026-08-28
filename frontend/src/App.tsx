import { useCallback, useEffect, useState } from "react";
import "./design/tokens.css";
import "./design/componentes.css";
import "./shell/shell.css";
import { api, sesion } from "./api/cliente";
import { ProveedorPlan } from "./plan/PlanContexto";
import { Landing } from "./landing/Landing";
import { Login } from "./Login";
import { Panel } from "./Panel";
import { PanelInterno } from "./interno/PanelInterno";
import { Cargando } from "./ui/Estados";

interface Yo {
  rol: string;
}

/** El rol decide el panel: el personal interno entra al suyo, el inquilino al
 *  del cliente. Es el servidor quien dice el rol; aquí solo se enruta. */
export default function App() {
  const [autenticado, setAutenticado] = useState(sesion.activa);
  const [mostrarLogin, setMostrarLogin] = useState(false);
  const [rol, setRol] = useState<string | null>(null);
  const [cargando, setCargando] = useState(sesion.activa);

  const identificar = useCallback(async () => {
    if (!sesion.activa) {
      setRol(null);
      setCargando(false);
      return;
    }
    setCargando(true);
    try {
      const yo = await api.get<Yo>("/auth/me");
      setRol(yo.rol);
    } catch {
      sesion.limpiar();
      setAutenticado(false);
      setRol(null);
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void identificar();
  }, [identificar, autenticado]);

  const salir = () => {
    sesion.limpiar();
    setRol(null);
    setAutenticado(false);
  };

  // Quien no ha entrado ve la web pública; el login se abre desde ella. Un
  // visitante no debería toparse con una pantalla de contraseña como portada.
  if (!autenticado) {
    return mostrarLogin ? (
      <Login onEntrar={() => setAutenticado(true)} onVolver={() => setMostrarLogin(false)} />
    ) : (
      <Landing onEntrar={() => setMostrarLogin(true)} />
    );
  }
  if (cargando || !rol) return <Cargando texto="Entrando…" />;

  if (rol === "SUPERADMIN" || rol === "SOPORTE" || rol === "LECTURA") {
    return <PanelInterno onSalir={salir} />;
  }

  return (
    <ProveedorPlan>
      <Panel onSalir={salir} />
    </ProveedorPlan>
  );
}
