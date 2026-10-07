$modelname "claudecol/estalactite.mdl"
$staticprop
$surfaceprop "rock"
$cdmaterials "models/claudecol/"
$body "body" "estalactite_phys.smd"
$sequence "idle" "estalactite_phys.smd"
$collisionmodel "estalactite_phys.smd"
{
	$concave
	$maxconvexpieces 64
	$mass 1000
}
