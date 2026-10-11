// MountainGate North/South: Unity editor helpers for the GSPro / OPCD hand-off (output/gspro/).
// Unity 2018.2.8f1 (the OPCD base project version); built-in render pipeline. Put this file in Assets/Editor/.
//
// Menu "MountainGate/...":
//   1. Build Terrains       inner + outer (OPCD 'Plot (Outer)') Unity terrains from the 16-bit RAW heightmaps and overlays
//   2. Place Trees          LiDAR trees from trees.csv as tree_prefabs.fbx objects (LOD groups) with trunk colliders
//   3. Water Reflection Probes   a realtime / on-awake reflection probe over every *_WaterPlane (OPCD guidance)
//   4. Add 3D Grass (3DG)   Stix Games Grass Renderer on *_SemiRough / *_Rough / *_DeepRough meshes, layer '600m cull'
// Run SetMeshMaterials (OPCD) on course_meshes.fbx as usual; the meshes carry OPCD names (Hole##_<Surface>).
// Files are read from the folder chosen in the window (default: Assets/MountainGate). Nothing here needs network access.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

public class MountainGateSetup : EditorWindow
{
    string dataDir = "Assets/MountainGate";
    string treeModelPath = "Assets/MountainGate/tree_prefabs.fbx";
    float treeMaxDistance = 0f;      // 0 = all trees; else only trees within this many metres of a course mesh
    bool treeColliders = true;
    Material grassSemiRough, grassRough, grassDeepRough;

    [MenuItem("MountainGate/Setup Window")]
    static void Open() { GetWindow<MountainGateSetup>("MountainGate"); }

    void OnGUI()
    {
        GUILayout.Label("Hand-off folder (contains terrain.json, trees.csv, ...)", EditorStyles.boldLabel);
        dataDir = EditorGUILayout.TextField("Data folder", dataDir);
        treeModelPath = EditorGUILayout.TextField("tree_prefabs.fbx", treeModelPath);
        GUILayout.Space(6);
        if (GUILayout.Button("1. Build Terrains (inner + outer)")) BuildTerrains(dataDir);
        GUILayout.Space(6);
        treeMaxDistance = EditorGUILayout.FloatField("Trees: max distance (m, 0 = all)", treeMaxDistance);
        treeColliders = EditorGUILayout.Toggle("Trees: trunk colliders", treeColliders);
        if (GUILayout.Button("2. Place Trees")) PlaceTrees(dataDir, treeModelPath, treeMaxDistance, treeColliders);
        GUILayout.Space(6);
        if (GUILayout.Button("3. Water Reflection Probes")) WaterProbes();
        GUILayout.Space(6);
        GUILayout.Label("3DG materials (from the OPCD base project; duplicate and tune)", EditorStyles.boldLabel);
        grassSemiRough = (Material)EditorGUILayout.ObjectField("Semi Rough", grassSemiRough, typeof(Material), false);
        grassRough = (Material)EditorGUILayout.ObjectField("Rough", grassRough, typeof(Material), false);
        grassDeepRough = (Material)EditorGUILayout.ObjectField("Deep Rough", grassDeepRough, typeof(Material), false);
        if (GUILayout.Button("4. Add 3D Grass (3DG)")) AddGrass(grassSemiRough, grassRough, grassDeepRough);
    }

    // ------------------------------------------------------------------ terrains
    [Serializable] class Size { public float width_x; public float length_z; public float height_y; }
    [Serializable] class Pos { public float x; public float y; public float z; }
    [Serializable] class Outer { public string heightmap; public int resolution; public string overlay; public Size terrain_size_m; public Pos unity_position; }
    [Serializable] class TerrainMeta { public string heightmap; public int resolution; public string overlay; public Size terrain_size_m; public Outer outer; }

    static float[,] ReadRaw16(string path, int n)
    {
        // RAW rows are north-first (GIS order); Unity's heights[0, *] is the south edge (z = 0): flip vertically.
        byte[] b = File.ReadAllBytes(path);
        if (b.Length != n * n * 2) throw new Exception(path + ": expected " + (n * n * 2) + " bytes, got " + b.Length);
        float[,] h = new float[n, n];
        for (int row = 0; row < n; row++)
            for (int col = 0; col < n; col++)
            {
                int i = 2 * (row * n + col);
                h[n - 1 - row, col] = (b[i] | (b[i + 1] << 8)) / 65535f;
            }
        return h;
    }

    static Terrain MakeTerrain(string dir, string name, string rawPath, int n, Size size, string overlayAsset, Vector3 position)
    {
        TerrainData td = new TerrainData();
        td.heightmapResolution = n;
        td.size = new Vector3(size.width_x, size.height_y, size.length_z);
        td.SetHeights(0, 0, ReadRaw16(rawPath, n));
        Texture2D tex = AssetDatabase.LoadAssetAtPath<Texture2D>(overlayAsset);
        if (tex != null)
        {
            // Unity 2018.2: splat prototypes (TerrainLayer arrives in 2018.3); one layer stretched over the whole terrain
            SplatPrototype sp = new SplatPrototype();
            sp.texture = tex;
            sp.tileSize = new Vector2(size.width_x, size.length_z);
            sp.tileOffset = Vector2.zero;
            td.splatPrototypes = new SplatPrototype[] { sp };
        }
        else Debug.LogWarning("Overlay not found: " + overlayAsset + " (set its import Max Size to 8192)");
        string dataPath = dir + "/" + name.Replace(" ", "").Replace("(", "_").Replace(")", "") + "_TerrainData.asset";
        AssetDatabase.CreateAsset(td, dataPath);
        GameObject go = Terrain.CreateTerrainGameObject(td);
        go.name = name;
        go.transform.position = position;
        return go.GetComponent<Terrain>();
    }

    static void BuildTerrains(string dir)
    {
        TerrainMeta m = JsonUtility.FromJson<TerrainMeta>(File.ReadAllText(Path.Combine(dir, "terrain.json")));
        MakeTerrain(dir, "Terrain (Inner)", Path.Combine(dir, m.heightmap), m.resolution, m.terrain_size_m,
                    dir + "/" + m.overlay, Vector3.zero);
        if (m.outer != null && !string.IsNullOrEmpty(m.outer.heightmap))
        {
            Terrain outer = MakeTerrain(dir, "Plot (Outer)", Path.Combine(dir, m.outer.heightmap), m.outer.resolution, m.outer.terrain_size_m,
                                        dir + "/" + m.outer.overlay, new Vector3(m.outer.unity_position.x, m.outer.unity_position.y, m.outer.unity_position.z));
            outer.basemapDistance = 20000f;
            outer.heightmapPixelError = 8f;
        }
        Debug.Log("MountainGate: terrains built (inner at the origin; course meshes and trees use the same frame)");
    }

    // ------------------------------------------------------------------ trees
    [Serializable] class Prefab { public string name; public string archetype; public float ref_height_m; public float ref_crown_radius_m; public float trunk_radius_m; public float crown_base_m; }
    [Serializable] class PrefabList { public Prefab[] prefabs; }

    static float F(string s) { return float.Parse(s, CultureInfo.InvariantCulture); }

    static void PlaceTrees(string dir, string modelPath, float maxDist, bool colliders)
    {
        GameObject model = AssetDatabase.LoadAssetAtPath<GameObject>(modelPath);
        if (model == null) { Debug.LogError("Tree model not found: " + modelPath); return; }
        Dictionary<string, Transform> protos = new Dictionary<string, Transform>();
        foreach (Transform t in model.GetComponentsInChildren<Transform>(true))
            if (t.name.StartsWith("Tree_") && !t.name.Contains("_LOD")) protos[t.name] = t;
        Dictionary<string, Prefab> info = new Dictionary<string, Prefab>();
        foreach (Prefab p in JsonUtility.FromJson<PrefabList>(File.ReadAllText(Path.Combine(dir, "tree_prefabs.json"))).prefabs) info[p.name] = p;

        List<Bounds> course = new List<Bounds>();
        if (maxDist > 0)
            foreach (MeshRenderer r in FindObjectsOfType<MeshRenderer>())
                if (r.name.StartsWith("Hole") && r.name.Length > 6 && char.IsDigit(r.name[4]) && int.Parse(r.name.Substring(4, 2)) <= 18)
                    course.Add(r.bounds);

        string[] lines = File.ReadAllLines(Path.Combine(dir, "trees.csv"));
        string[] head = lines[0].Split(',');
        Func<string, int> col = (k) => Array.IndexOf(head, k);
        int cPrefab = col("prefab"), cx = col("unity_x"), cy = col("unity_y"), cz = col("unity_z"), cYaw = col("yaw_deg"),
            cSxz = col("scale_xz"), cSy = col("scale_y");
        GameObject root = new GameObject("MountainGate_Trees");
        Dictionary<string, Transform> cells = new Dictionary<string, Transform>();
        int placed = 0;
        for (int i = 1; i < lines.Length; i++)
        {
            string[] v = lines[i].Split(',');
            Transform proto;
            if (!protos.TryGetValue(v[cPrefab], out proto)) continue;
            Vector3 pos = new Vector3(F(v[cx]), F(v[cy]), F(v[cz]));
            if (maxDist > 0 && !course.Any(b => b.SqrDistance(pos) < maxDist * maxDist)) continue;
            string cellKey = ((int)(pos.x / 256f)) + "_" + ((int)(pos.z / 256f));
            Transform cell;
            if (!cells.TryGetValue(cellKey, out cell))
            {
                cell = new GameObject("Cell_" + cellKey).transform; cell.SetParent(root.transform, false); cells[cellKey] = cell;
            }
            GameObject t = (GameObject)Instantiate(proto.gameObject, pos, Quaternion.Euler(0f, F(v[cYaw]), 0f), cell);
            t.name = proto.name;
            float sxz = F(v[cSxz]), sy = F(v[cSy]);
            t.transform.localScale = new Vector3(sxz, sy, sxz);
            if (t.GetComponent<LODGroup>() == null) AddLodGroup(t);
            Prefab p;
            if (colliders && info.TryGetValue(proto.name, out p) && p.archetype != "shrub")
            {
                // ball physics: a trunk capsule up to the crown base (canopy left open, as most designers do)
                CapsuleCollider cc = t.AddComponent<CapsuleCollider>();
                cc.direction = 1;
                cc.radius = p.trunk_radius_m;
                cc.height = Mathf.Max(p.crown_base_m, 2f * p.trunk_radius_m);
                cc.center = new Vector3(0f, cc.height / 2f, 0f);
            }
            GameObjectUtility.SetStaticEditorFlags(t, StaticEditorFlags.BatchingStatic | StaticEditorFlags.OccluderStatic | StaticEditorFlags.OccludeeStatic);
            placed++;
        }
        Debug.Log("MountainGate: placed " + placed + " trees in " + cells.Count + " cells");
    }

    static void AddLodGroup(GameObject t)
    {
        // fallback if the FBX importer did not build the LOD Group from the _LOD0/_LOD1/_LOD2 children
        List<LOD> lods = new List<LOD>();
        float[] screen = { 0.25f, 0.06f, 0.008f };
        for (int k = 0; k < 3; k++)
        {
            Transform c = t.transform.Find(t.name + "_LOD" + k);
            if (c == null) continue;
            lods.Add(new LOD(screen[k], c.GetComponentsInChildren<Renderer>()));
        }
        if (lods.Count == 0) return;
        LODGroup g = t.AddComponent<LODGroup>();
        g.SetLODs(lods.ToArray());
        g.RecalculateBounds();
    }

    // ------------------------------------------------------------------ water
    static void WaterProbes()
    {
        int n = 0;
        foreach (MeshRenderer r in FindObjectsOfType<MeshRenderer>())
        {
            if (!r.name.Contains("_WaterPlane")) continue;
            GameObject go = new GameObject(r.name + "_ReflectionProbe");
            go.transform.position = r.bounds.center + Vector3.up * 2f;
            ReflectionProbe p = go.AddComponent<ReflectionProbe>();
            p.mode = UnityEngine.Rendering.ReflectionProbeMode.Realtime;
            p.refreshMode = UnityEngine.Rendering.ReflectionProbeRefreshMode.OnAwake;   // GSPro refreshes probes on time/weather changes
            p.timeSlicingMode = UnityEngine.Rendering.ReflectionProbeTimeSlicingMode.NoTimeSlicing;
            p.size = new Vector3(r.bounds.size.x + 40f, 60f, r.bounds.size.z + 40f);
            p.resolution = 256;
            p.boxProjection = false;
            p.farClipPlane = 5000f;   // keep the mountains in the reflection
            n++;
        }
        Debug.Log("MountainGate: " + n + " water reflection probes");
    }

    // ------------------------------------------------------------------ 3D grass
    static Type FindType(string name)
    {
        foreach (System.Reflection.Assembly a in AppDomain.CurrentDomain.GetAssemblies())
            foreach (Type t in SafeTypes(a))
                if (t.Name == name && typeof(Component).IsAssignableFrom(t)) return t;
        return null;
    }

    static IEnumerable<Type> SafeTypes(System.Reflection.Assembly a)
    {
        try { return a.GetTypes(); } catch (System.Reflection.ReflectionTypeLoadException e) { return e.Types.Where(t => t != null); }
    }

    static void AddGrass(Material semi, Material rough, Material deep)
    {
        Type renderer = FindType("GrassRenderer");
        if (renderer == null) { Debug.LogError("Stix Games 'Grass Renderer' not found: install the DirectX 11 Grass Shader (3DG) first"); return; }
        int layer = LayerMask.NameToLayer("600m cull");
        if (layer < 0) Debug.LogWarning("Layer '600m cull' not found (it comes with the OPCD base project)");
        int n = 0;
        foreach (MeshRenderer r in FindObjectsOfType<MeshRenderer>())
        {
            string nm = r.name;
            Material m = nm.Contains("_SemiRough") ? semi : nm.Contains("_DeepRough") ? deep : nm.Contains("_Rough") ? rough : null;
            if (m == null && !(nm.Contains("_SemiRough") || nm.Contains("_DeepRough") || nm.Contains("_Rough"))) continue;
            GameObject go = r.gameObject;
            Component c = go.GetComponent(renderer);
            if (c == null) c = go.AddComponent(renderer);   // also adds the Nature Mesh Filter
            if (m != null) AssignMaterial(c, m);
            if (layer >= 0) go.layer = layer;
            n++;
        }
        Debug.Log("MountainGate: 3DG on " + n + " meshes. The meshes' colour layer 'Col' holds 3DG vertex densities " +
                  "(R = grass type 1, G = type 2 / dry): set each 3DG material's Density Mode to 'Vertex density'. See grass_3dg.json.");
    }

    static void AssignMaterial(Component c, Material m)
    {
        // the Grass Renderer's material field name is not documented publicly: set the first Material-typed field/property
        SerializedObject so = new SerializedObject(c);
        SerializedProperty it = so.GetIterator();
        while (it.NextVisible(true))
        {
            if (it.propertyType == SerializedPropertyType.ObjectReference && it.type.Contains("Material"))
            {
                it.objectReferenceValue = m;
                so.ApplyModifiedProperties();
                return;
            }
        }
        Debug.LogWarning(c.name + ": assign the 3DG material by hand (no Material field found on " + c.GetType().Name + ")");
    }
}
