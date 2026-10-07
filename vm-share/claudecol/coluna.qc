$modelname "claudecol/coluna.mdl"
$staticprop
$surfaceprop "dirt"
$cdmaterials "models/claudecol/"
$body "body" "coluna_phys.smd"
$sequence "idle" "coluna_phys.smd"
$collisionmodel "coluna_phys.smd"
{
	$concave
	$maxconvexpieces 64
	$mass 1000
}
