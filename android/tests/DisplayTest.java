package com.dsefa.flir;
import java.util.*;
import java.lang.reflect.*;
public class DisplayTest {
 static int checks;
 static void check(boolean v,String message){checks++;if(!v)throw new AssertionError(message);}
 static Class<?> rendererClass;
 static Object renderer() throws Exception {return rendererClass.getDeclaredConstructor().newInstance();}
 static int[] render(Object r,double[] t,Thermal.Settings s,long ms)throws Exception{return (int[])rendererClass.getMethod("render",double[].class,Thermal.Settings.class,long.class).invoke(r,t,s,ms);}
 static double field(Object r,String name)throws Exception{return rendererClass.getField(name).getDouble(r);}
 static void setting(Thermal.Settings s,String key,Object v)throws Exception{s.getClass().getField(key).set(s,v);}
 static int gray(int color){return color&255;}
 static double[] scene(double t){double[] a=new double[19200];Arrays.fill(a,t);return a;}
 public static void main(String[] args)throws Exception{
  try{rendererClass=Class.forName("com.dsefa.flir.Thermal$Renderer");}catch(ClassNotFoundException e){throw new AssertionError("Stateful display renderer is missing");}
  Thermal.Settings s=new Thermal.Settings();s.palette="White hot";s.scale="Manual";s.low=10;s.high=30;
  double[] t=scene(20);t[0]=10;t[1]=30;t[2]=Double.NaN;double[] original=t.clone();
  setting(s,"denoise",100.0);Object r=renderer();int[] c=render(r,t,s,1000);
  check(gray(c[0])==0&&gray(c[1])==255&&gray(c[2])==0,"Manual endpoints and invalid samples bypass display filtering");
  check(Arrays.equals(t,original),"Display never mutates radiometric input");
  check(field(r,"low")==10&&field(r,"high")==30,"Manual legend reports exact endpoints");
  s.span=200;c=render(renderer(),new double[]{0,10,20,30,40},s,1000);check(gray(c[0])==0&&gray(c[4])==255,"Expanded manual span preserves temperatures outside original bounds");s.span=100;
  s.scale="Linear auto";setting(s,"denoise",0.0);render(r,scene(20),s,1000);double first=field(r,"low");
  render(r,scene(21),s,1000);check(field(r,"low")==first,"Frozen timestamp must not evolve adaptive range");
  render(r,scene(21),s,1100);check(field(r,"low")>first&&field(r,"low")<20.25,"Range evolves gradually on advancing time");
  render(r,scene(19),s,500);check(Math.abs(field(r,"low")-18.25)<1e-9,"Rewind resets adaptive range");
  render(r,scene(50),s,600);check(Math.abs(field(r,"low")-49.25)<1e-9,"Scene cut adapts immediately");
  double[] ramp=new double[19200];for(int i=0;i<ramp.length;i++)ramp[i]=20+(i%160)/159.0;
  s.scale="Auto";Object auto=renderer();int[] a=render(auto,ramp,s,1000);
  for(int x=1;x<160;x++)check(gray(a[x])>=gray(a[x-1]),"Plateau histogram mapping is monotone");
  s.scale="Detail";setting(s,"detail",100.0);int[] d=render(renderer(),ramp,s,1000);
  check(!Arrays.equals(a,d),"Detail uses local contrast rather than global Auto mapping");
  for(int x=41;x<79;x++)check(gray(d[x])>=gray(d[x-1]),"Local tile detail remains monotone on a ramp");
  for(int color:d)check((color>>>24)==255,"Detail palette is opaque and bounded");
  for(String mode:(String[])Thermal.class.getField("MODES").get(null)){s.scale=mode;int[] constant=render(renderer(),scene(20),s,1000);check(constant[0]==constant[19199],"Constant scene uniform in "+mode);}
  s.scale="Background relative";Object bg=renderer();render(bg,scene(20),s,1000);render(bg,scene(21),s,1000);
  check(field(bg,"background")==20,"Paused background cannot continue learning");
  render(bg,scene(21),s,2000);check(field(bg,"background")>20&&field(bg,"background")<21,"Background learns slowly");
  render(bg,scene(18),s,500);check(field(bg,"background")==18,"Background resets on rewind");
  rendererClass.getMethod("reset").invoke(bg);render(bg,scene(22),s,3000);check(field(bg,"background")==22,"Explicit reset discards learned scene");
  double[] hot=scene(20);hot[100]=24;c=render(renderer(),hot,s,1000);check(gray(c[0])<32&&gray(c[100])>200,"Background stays dark while warm spot is visible");
  double[] bad=scene(Double.NaN);c=render(renderer(),bad,s,1000);check(c[0]==0xff000000&&Double.isFinite(field(renderer(),"low")),"Invalid scene has safe black output and finite defaults");
  setting(s,"fahrenheit",true);double fahrenheit=(Double)Thermal.class.getMethod("displayTemperature",double.class,Thermal.Settings.class).invoke(null,20.0,s);
  check(fahrenheit==68,"Fahrenheit converts presentation only");
  String label=(String)Thermal.class.getMethod("formatTemperature",double.class,Thermal.Settings.class).invoke(null,20.0,s);check(label.contains("68.0")&&label.contains("F"),"Temperature labels include converted value and unit");
  t=scene(20);t[0]=29;Method sample=Thermal.class.getMethod("sample",double[].class,int.class,boolean.class);
  check((Double)sample.invoke(null,t,0,false)==29,"Single sampling preserves exact pixel");check(Math.abs((Double)sample.invoke(null,t,0,true)-22.25)<1e-9,"Corner average uses four available neighbors");
  Thermal.Settings copy=s.copy();setting(copy,"hotSpan",8.0);check(s.getClass().getField("hotSpan").getDouble(s)==3,"Settings copy is independent");
  s.scale="Linear auto";s.palette="White hot";setting(s,"minSpan",4.0);Object floorRenderer=renderer();render(floorRenderer,scene(20),s,0);
  check(field(floorRenderer,"low")==18&&field(floorRenderer,"high")==22,"Minimum span bounds low contrast scenes");
  setting(s,"smooth",false);render(floorRenderer,scene(21),s,1);check(field(floorRenderer,"low")==19,"Disabled smoothing applies new range immediately");
  s.scale="Manual";s.low=30;s.high=10;boolean rejected=false;try{render(renderer(),scene(20),s,0);}catch(InvocationTargetException e){rejected=e.getCause() instanceof IllegalArgumentException;}check(rejected,"Reversed manual endpoints are rejected clearly");s.low=10;s.high=30;
  setting(s,"average",false);setting(s,"smooth",false);setting(s,"contrast",3.0);setting(s,"minSpan",4.0);setting(s,"detail",76.0);setting(s,"denoise",22.0);setting(s,"deadband",.8);setting(s,"learningSeconds",60.0);
  copy=s.copy();for(String option:new String[]{"contrast","minSpan","detail","denoise","deadband","hotSpan","learningSeconds","average","smooth","fahrenheit"})check(s.getClass().getField(option).get(s).equals(s.getClass().getField(option).get(copy)),"Copied display option persists: "+option);
  for(String p:(String[])Thermal.class.getField("PALETTES").get(null)){s.palette=p;s.scale="Manual";c=render(renderer(),new double[]{10,20,30},s,1000);check(c[0]!=c[2]&&(c[1]>>>24)==255,"Palette spans visible opaque colors: "+p);}
  System.out.println("PASS "+checks+" display checks");
 }
}
