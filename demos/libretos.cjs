// Lectura de los libretos (demos/libretos/*.yml) para los scripts de demos, y las rutas de las herramientas externas.
// Node no trae YAML: se usa el ruby del sistema, que sí. Las herramientas van con ruta absoluta (no se buscan en el PATH);
// RUBY y FFMPEG permiten apuntar a otra instalación.
const { execFileSync } = require("node:child_process");
const path = require("node:path");

const RAIZ = path.resolve(__dirname, "..");
const RUBY = process.env.RUBY ?? "/usr/bin/ruby";
const FFMPEG = process.env.FFMPEG ?? "/opt/homebrew/bin/ffmpeg";

/** { feature: libreto } con todos los libretos, ordenados por nombre de archivo. */
function leerLibretos() {
  const ruby = 'puts JSON.dump(Dir["demos/libretos/*.yml"].sort.to_h { |f| d = YAML.load_file(f); [d["feature"], d] })';
  return JSON.parse(execFileSync(RUBY, ["-ryaml", "-rjson", "-e", ruby], { cwd: RAIZ, encoding: "utf8" }));
}

module.exports = { RAIZ, FFMPEG, leerLibretos };
