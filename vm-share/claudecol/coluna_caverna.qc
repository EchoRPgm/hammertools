$modelname "claudecol/coluna_caverna.mdl"
$staticprop
$surfaceprop "concrete"
$cdmaterials "models/claudecol/"
$body "body" "coluna_caverna_phys.smd"
$sequence "idle" "coluna_caverna_phys.smd"
$collisionmodel "coluna_caverna_phys.smd"
{
	$concave
	$maxconvexpieces 64
	$mass 1000
}
