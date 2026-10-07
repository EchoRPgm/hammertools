$modelname "claudecol/cassino.mdl"
$staticprop
$surfaceprop "metal"
$cdmaterials "models/claudecol/"
$body "body" "cassino_phys.smd"
$sequence "idle" "cassino_phys.smd"
$collisionmodel "cassino_phys.smd"
{
	$concave
	$maxconvexpieces 64
	$mass 1000
}
